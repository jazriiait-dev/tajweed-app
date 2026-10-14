import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api/api.dart';
import '../api/models.dart';
import 'stores.dart';

/// A child profile a parent has opened on this device.
class ActiveChild {
  ActiveChild({required this.child, required this.user, required this.token});

  final Child child;
  final User user;
  String token;
}

/// Who is signed in, the tokens, and the chosen language.
///
/// Every call that needs a sign-in goes through [authed], which renews an
/// expired access token once and retries. Renewals are shared: if several
/// calls find the token expired at the same time, only one renewal is made,
/// because the API treats a refresh token presented twice as stolen.
class Session extends ChangeNotifier {
  Session({
    required this.api,
    required this.secrets,
    required this.prefs,
    String initialLanguage = 'en',
  }) : language = initialLanguage;

  static const languages = ['ar', 'en', 'fr'];
  static const _refreshKey = 'refresh_token';
  static const _languageKey = 'language';

  final Api api;
  final KeyValueStore secrets;
  final KeyValueStore prefs;

  String language;
  bool restoring = true;

  User? user;
  ActiveChild? activeChild;

  String? _access;
  String? _refresh;
  Future<void>? _refreshing;

  bool get signedIn => user != null;
  bool get isAdult => signedIn && activeChild == null;

  /// The person using the app right now: the signed-in adult, or the child they opened.
  User? get currentUser => activeChild?.user ?? user;

  bool has(String role) => currentUser?.has(role) ?? false;

  // --- starting up ---------------------------------------------------------------

  Future<void> restore() async {
    final saved = await prefs.read(_languageKey);
    if (saved != null && languages.contains(saved)) language = saved;

    _refresh = await secrets.read(_refreshKey);
    if (_refresh != null) {
      try {
        await _renewTokens();
        user = User.fromJson(await api.me(_access!));
      } on ApiException catch (error) {
        // Signed out on the server, or the token is no longer valid.
        // A network failure keeps the token, so the next launch can try again.
        if (error.status == 401 || error.status == 403) await _forget();
      }
    }
    restoring = false;
    notifyListeners();
  }

  // --- language --------------------------------------------------------------------

  Future<void> setLanguage(String code) async {
    if (!languages.contains(code) || code == language) return;
    language = code;
    notifyListeners();
    await prefs.write(_languageKey, code);
    if (isAdult) {
      try {
        user = User.fromJson(await authed((token) => api.updateMe(token, {'language': code})));
        notifyListeners();
      } on ApiException {
        // The language still changes on this device; the account keeps the old one.
      }
    }
  }

  // --- signing in and out --------------------------------------------------------------

  Future<void> signIn(String email, String password) async {
    await _start(await api.login(email, password));
  }

  Future<void> register({
    required String email,
    required String password,
    required String displayName,
    required String accountType,
  }) async {
    await _start(await api.register({
      'email': email,
      'password': password,
      'display_name': displayName,
      'account_type': accountType,
      'language': language,
      'confirms_adult': true,
    }));
  }

  Future<void> _start(Map<String, dynamic> result) async {
    await _keepTokens(result);
    user = User.fromJson((result['user'] as Map).cast<String, dynamic>());
    activeChild = null;
    if (languages.contains(user!.language) && user!.language != language) {
      language = user!.language;
      await prefs.write(_languageKey, language);
    }
    notifyListeners();
  }

  Future<void> signOut() async {
    final token = _refresh;
    if (token != null) {
      try {
        await api.logout(token);
      } on ApiException {
        // Signed out on this device either way.
      }
    }
    await _forget();
    notifyListeners();
  }

  Future<void> updateProfile({String? displayName}) async {
    final changes = <String, Object?>{};
    if (displayName != null) changes['display_name'] = displayName;
    user = User.fromJson(await authed((token) => api.updateMe(token, changes)));
    notifyListeners();
  }

  // --- child profiles ---------------------------------------------------------------------

  Future<void> openChild(Child child) async {
    final result = await adult((token) => api.openChild(token, child.id));
    activeChild = ActiveChild(
      child: child,
      user: User.fromJson((result['user'] as Map).cast<String, dynamic>()),
      token: result['access_token'] as String,
    );
    notifyListeners();
  }

  void closeChild() {
    activeChild = null;
    notifyListeners();
  }

  // --- calls that need a sign-in ---------------------------------------------------------------

  /// Runs [call] as the current user: the opened child if there is one, else the adult.
  Future<T> authed<T>(Future<T> Function(String token) call) async {
    final child = activeChild;
    if (child == null) return adult(call);
    try {
      return await call(child.token);
    } on ApiException catch (error) {
      if (error.code != 'session_expired') rethrow;
      // A child's access ends after an hour; the parent's account reopens it.
      final result = await adult((token) => api.openChild(token, child.child.id));
      child.token = result['access_token'] as String;
      return call(child.token);
    }
  }

  /// Runs [call] as the signed-in adult, even while a child profile is open.
  Future<T> adult<T>(Future<T> Function(String token) call) async {
    final access = _access;
    if (access == null) throw ApiException(401, 'not_signed_in');
    try {
      return await call(access);
    } on ApiException catch (error) {
      if (error.code == 'session_expired') {
        // Another call may already have renewed the token; only renew if not.
        if (_access == access) await _renewOrSignOut();
        final renewed = _access;
        if (renewed == null) rethrow;
        return call(renewed);
      }
      if (error.status == 401 || error.code == 'account_disabled') {
        await _forget();
        notifyListeners();
      }
      rethrow;
    }
  }

  /// For pages open to everyone: signed-in users send their token, so admins
  /// can also see texts that are waiting for review.
  Future<T> maybeAuthed<T>(Future<T> Function(String? token) call) =>
      signedIn ? authed(call) : call(null);

  Future<void> _renewOrSignOut() async {
    try {
      await _renewTokens();
    } on ApiException catch (error) {
      if (error.status == 401 || error.status == 403) {
        await _forget();
        notifyListeners();
      }
      rethrow;
    }
  }

  Future<void> _renewTokens() {
    return _refreshing ??= _doRenew().whenComplete(() => _refreshing = null);
  }

  Future<void> _doRenew() async {
    final token = _refresh;
    if (token == null) throw ApiException(401, 'not_signed_in');
    await _keepTokens(await api.refresh(token));
  }

  Future<void> _keepTokens(Map<String, dynamic> result) async {
    _access = result['access_token'] as String;
    _refresh = result['refresh_token'] as String;
    await secrets.write(_refreshKey, _refresh);
  }

  Future<void> _forget() async {
    user = null;
    activeChild = null;
    _access = null;
    _refresh = null;
    await secrets.write(_refreshKey, null);
  }
}
