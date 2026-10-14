import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// An error reported by the API, or a failure to reach it.
///
/// [code] is the API's stable error code (see docs/API.md); the app translates it.
class ApiException implements Exception {
  ApiException(this.status, this.code, [this.message = '', this.details]);

  final int status;
  final String code;
  final String message;
  final Object? details;

  @override
  String toString() => 'ApiException($status, $code)';
}

/// Thin wrapper around the HTTP API. One method per route the app uses.
class Api {
  Api({required this.base, http.Client? client}) : _http = client ?? http.Client();

  final Uri base;
  final http.Client _http;

  static const _timeout = Duration(seconds: 30);

  Uri _uri(String path, Map<String, String>? query) {
    var prefix = base.path;
    if (prefix.endsWith('/')) prefix = prefix.substring(0, prefix.length - 1);
    return base.replace(
      path: '$prefix/api/v1$path',
      queryParameters: (query == null || query.isEmpty) ? null : query,
    );
  }

  Future<dynamic> send(
    String method,
    String path, {
    Object? body,
    String? token,
    Map<String, String>? query,
  }) async {
    final request = http.Request(method, _uri(path, query));
    request.headers['Accept'] = 'application/json';
    if (token != null) request.headers['Authorization'] = 'Bearer $token';
    if (body != null) {
      request.headers['Content-Type'] = 'application/json';
      request.body = jsonEncode(body);
    }

    final http.Response response;
    try {
      final streamed = await _http.send(request).timeout(_timeout);
      response = await http.Response.fromStream(streamed).timeout(_timeout);
    } catch (_) {
      throw ApiException(0, 'network_error');
    }

    if (response.statusCode == 204) return null;
    dynamic decoded;
    if (response.bodyBytes.isNotEmpty) {
      try {
        decoded = jsonDecode(utf8.decode(response.bodyBytes));
      } catch (_) {
        decoded = null;
      }
    }
    if (response.statusCode >= 200 && response.statusCode < 300) return decoded;

    final Map error = (decoded is Map && decoded['error'] is Map) ? decoded['error'] as Map : const {};
    throw ApiException(
      response.statusCode,
      (error['code'] ?? 'http_error').toString(),
      (error['message'] ?? '').toString(),
      error['details'],
    );
  }

  Map<String, dynamic> _map(dynamic value) => (value as Map).cast<String, dynamic>();

  List<Map<String, dynamic>> _list(dynamic value) =>
      (value as List).map((item) => (item as Map).cast<String, dynamic>()).toList();

  // --- signing in --------------------------------------------------------------

  Future<Map<String, dynamic>> register(Map<String, Object?> data) async =>
      _map(await send('POST', '/auth/register', body: data));

  Future<Map<String, dynamic>> login(String email, String password) async =>
      _map(await send('POST', '/auth/login', body: {'email': email, 'password': password}));

  Future<Map<String, dynamic>> refresh(String refreshToken) async =>
      _map(await send('POST', '/auth/refresh', body: {'refresh_token': refreshToken}));

  Future<void> logout(String refreshToken) =>
      send('POST', '/auth/logout', body: {'refresh_token': refreshToken});

  // --- my account ----------------------------------------------------------------

  Future<Map<String, dynamic>> me(String token) async => _map(await send('GET', '/me', token: token));

  Future<Map<String, dynamic>> updateMe(String token, Map<String, Object?> changes) async =>
      _map(await send('PATCH', '/me', token: token, body: changes));

  // --- children --------------------------------------------------------------------

  Future<List<Map<String, dynamic>>> children(String token) async =>
      _list(await send('GET', '/children', token: token));

  Future<Map<String, dynamic>> createChild(String token, Map<String, Object?> data) async =>
      _map(await send('POST', '/children', token: token, body: data));

  Future<Map<String, dynamic>> openChild(String token, String childId) async =>
      _map(await send('POST', '/children/$childId/session', token: token));

  // --- the Quran ---------------------------------------------------------------------

  Future<List<Map<String, dynamic>>> riwayat(String? token) async =>
      _list(await send('GET', '/riwayat', token: token));

  Future<Map<String, dynamic>> surahs(String? token, String riwaya) async =>
      _map(await send('GET', '/quran/$riwaya/surahs', token: token));

  Future<Map<String, dynamic>> surah(String? token, String riwaya, int number) async =>
      _map(await send('GET', '/quran/$riwaya/surahs/$number', token: token));

  // --- admin ---------------------------------------------------------------------------

  Future<Map<String, dynamic>> approveRiwaya(String token, String code, String reviewerName) async =>
      _map(await send('POST', '/admin/riwayat/$code/approve',
          token: token, body: {'reviewer_name': reviewerName}));
}
