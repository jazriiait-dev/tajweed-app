import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:tajweed_app/api/api.dart';
import 'package:tajweed_app/app.dart';
import 'package:tajweed_app/state/session.dart';
import 'package:tajweed_app/state/stores.dart';

/// A small stand-in for the real API, enough for the app's tests.
///
/// It follows the API's rules that the app depends on: tokens that expire,
/// refresh tokens that work once, children that belong to one parent.
/// The "ayat" are placeholder words, never Quran text.
class FakeBackend {
  final Map<String, Map<String, dynamic>> users = {};
  final Map<String, String> passwords = {};
  final Map<String, List<String>> childrenOf = {};

  /// access token -> user id
  final Map<String, String> accessTokens = {};

  /// refresh token -> user id; a used token is removed.
  final Map<String, String> refreshTokens = {};

  /// Access tokens that the server now treats as expired.
  final Set<String> expired = {};

  final List<String> calls = [];
  int refreshCalls = 0;
  int _next = 0;

  String hafsStatus = 'approved';
  String? reviewer;

  String _id(String prefix) => '$prefix-${_next++}';

  Map<String, dynamic> addUser(String email, String password, String name, List<String> roles,
      {String language = 'en'}) {
    final id = _id('user');
    users[id] = {
      'id': id,
      'email': email,
      'display_name': name,
      'language': language,
      'roles': roles,
      'is_child': false,
      'is_active': true,
    };
    passwords[email] = password;
    return users[id]!;
  }

  Map<String, dynamic> _tokens(String userId) {
    final access = _id('access');
    final refresh = _id('refresh');
    accessTokens[access] = userId;
    refreshTokens[refresh] = userId;
    return {'access_token': access, 'refresh_token': refresh, 'expires_in': 1800, 'user': users[userId]};
  }

  /// Expires every access token handed out so far.
  void expireAll() => expired.addAll(accessTokens.keys);

  http.Client get client => MockClient(handle);

  Future<http.Response> handle(http.Request request) async {
    final path = request.url.path.replaceFirst('/api/v1', '');
    calls.add('${request.method} $path');
    final body = request.body.isEmpty ? <String, dynamic>{} : jsonDecode(request.body) as Map<String, dynamic>;
    final header = request.headers['Authorization'];
    final token = header?.startsWith('Bearer ') == true ? header!.substring(7) : null;

    http.Response json(Object? value, [int status = 200]) => http.Response.bytes(
          utf8.encode(jsonEncode(value)),
          status,
          headers: {'content-type': 'application/json'},
        );
    http.Response error(int status, String code) => json({
          'error': {'code': code, 'message': code}
        }, status);

    String? userId;
    if (token != null) {
      if (expired.contains(token)) return error(401, 'session_expired');
      userId = accessTokens[token];
      if (userId == null) return error(401, 'invalid_token');
    }
    Map<String, dynamic>? me = userId == null ? null : users[userId];

    switch ('${request.method} $path') {
      case 'POST /auth/login':
        final match = users.values.where((u) => u['email'] == body['email']).toList();
        if (match.isEmpty || passwords[body['email']] != body['password']) {
          return error(401, 'wrong_credentials');
        }
        return json(_tokens(match.first['id'] as String));
      case 'POST /auth/register':
        if (passwords.containsKey(body['email'])) return error(409, 'email_taken');
        final user = addUser(body['email'] as String, body['password'] as String, body['display_name'] as String,
            [body['account_type'] as String],
            language: body['language'] as String);
        return json(_tokens(user['id'] as String), 201);
      case 'POST /auth/refresh':
        refreshCalls++;
        final owner = refreshTokens.remove(body['refresh_token']);
        if (owner == null) return error(401, 'refresh_token_reused');
        return json(_tokens(owner));
      case 'POST /auth/logout':
        refreshTokens.remove(body['refresh_token']);
        return http.Response('', 204);
      case 'GET /me':
        if (me == null) return error(401, 'not_signed_in');
        return json(me);
      case 'PATCH /me':
        if (me == null) return error(401, 'not_signed_in');
        if (me['is_child'] == true) return error(403, 'managed_by_parent');
        me.addAll(body);
        return json(me);
      case 'GET /children':
        if (me == null) return error(401, 'not_signed_in');
        return json([for (final id in childrenOf[userId] ?? <String>[]) users[id]]);
      case 'POST /children':
        if (me == null) return error(401, 'not_signed_in');
        if (body['guardian_consent'] != true) return error(400, 'consent_required');
        final id = _id('child');
        users[id] = {
          'id': id,
          'email': null,
          'display_name': body['display_name'],
          'language': body['language'],
          'roles': ['student'],
          'is_child': true,
          'is_active': true,
        };
        childrenOf.putIfAbsent(userId!, () => []).add(id);
        return json(users[id], 201);
      case 'GET /riwayat':
        final isAdmin = (me?['roles'] as List?)?.contains('admin') ?? false;
        return json([
          {
            'code': 'hafs',
            'name': {'ar': 'حفص عن عاصم', 'en': 'Hafs from Asim', 'fr': "Hafs d'après Asim"},
            'available': hafsStatus == 'approved',
            if (isAdmin) ...{'status': hafsStatus, 'ayah_count': 6236, 'reviewer_name': reviewer},
          },
          {
            'code': 'warsh',
            'name': {'ar': 'ورش عن نافع', 'en': 'Warsh from Nafi', 'fr': "Warsh d'après Nafi"},
            'available': false,
            if (isAdmin) ...{'status': 'empty', 'ayah_count': null, 'reviewer_name': null},
          },
        ]);
      case 'POST /admin/riwayat/hafs/approve':
        if (!((me?['roles'] as List?)?.contains('admin') ?? false)) return error(403, 'not_allowed');
        hafsStatus = 'approved';
        reviewer = body['reviewer_name'] as String;
        return json({'code': 'hafs', 'status': 'approved'});
    }

    final childSession = RegExp(r'^POST /children/([^/]+)/session$').firstMatch('${request.method} $path');
    if (childSession != null) {
      final childId = childSession.group(1)!;
      if (me == null) return error(401, 'not_signed_in');
      if (!(childrenOf[userId] ?? const []).contains(childId)) return error(404, 'child_not_found');
      final access = _id('child-access');
      accessTokens[access] = childId;
      return json({'user': users[childId], 'access_token': access, 'expires_in': 3600});
    }

    final readable = hafsStatus == 'approved' || ((me?['roles'] as List?)?.contains('admin') ?? false);
    if (path == '/quran/hafs/surahs' && request.method == 'GET') {
      if (!readable) return error(404, 'riwaya_not_available');
      return json({
        'riwaya': 'hafs',
        'approved': hafsStatus == 'approved',
        'text_source': 'Test source',
        'text_notice': 'Test notice',
        'surahs': [
          {'number': 1, 'name_ar': 'الفاتحة', 'name_latin': 'Al-Fatihah', 'ayah_count': 7},
          {'number': 112, 'name_ar': 'الإخلاص', 'name_latin': 'Al-Ikhlas', 'ayah_count': 4},
        ],
      });
    }
    final surah = RegExp(r'^/quran/hafs/surahs/(\d+)$').firstMatch(path);
    if (surah != null && request.method == 'GET') {
      if (!readable) return error(404, 'riwaya_not_available');
      final number = int.parse(surah.group(1)!);
      final count = number == 1 ? 7 : 4;
      return json({
        'riwaya': 'hafs',
        'approved': hafsStatus == 'approved',
        'number': number,
        'name_ar': number == 1 ? 'الفاتحة' : 'الإخلاص',
        'name_latin': number == 1 ? 'Al-Fatihah' : 'Al-Ikhlas',
        'ayah_count': count,
        'ayahs': [
          for (var i = 1; i <= count; i++) {'number': i, 'text': 'placeholder $number:$i'}
        ],
      });
    }
    return error(404, 'not_found');
  }
}

/// A session wired to [backend], with in-memory storage.
Session testSession(FakeBackend backend, {MemoryStore? secrets, MemoryStore? prefs, String language = 'en'}) {
  return Session(
    api: Api(base: Uri.parse('https://api.test/'), client: backend.client),
    secrets: secrets ?? MemoryStore(),
    prefs: prefs ?? MemoryStore(),
    initialLanguage: language,
  );
}

/// Starts the app the way main() does, and waits until it has settled.
Future<Session> startApp(WidgetTester tester, FakeBackend backend,
    {MemoryStore? secrets, MemoryStore? prefs, String language = 'en'}) async {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 2.5;
  addTearDown(tester.view.reset);
  final session = testSession(backend, secrets: secrets, prefs: prefs, language: language);
  await tester.pumpWidget(TajweedApp(session: session));
  await session.restore();
  await tester.pumpAndSettle();
  return session;
}

Future<void> enter(WidgetTester tester, String key, String text) async {
  await tester.enterText(find.byKey(Key(key)), text);
}

Future<void> tap(WidgetTester tester, String key) async {
  await tester.ensureVisible(find.byKey(Key(key)));
  await tester.tap(find.byKey(Key(key)));
  await tester.pumpAndSettle();
}

Future<void> signInAs(WidgetTester tester, String email, String password) async {
  await tap(tester, 'go_sign_in');
  await enter(tester, 'email', email);
  await enter(tester, 'password', password);
  await tap(tester, 'submit');
}
