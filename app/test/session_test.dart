import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:tajweed_app/api/api.dart';
import 'package:tajweed_app/api/models.dart';
import 'package:tajweed_app/state/session.dart';
import 'package:tajweed_app/state/stores.dart';

import 'fake_backend.dart';

void main() {
  late FakeBackend backend;

  setUp(() {
    backend = FakeBackend();
    backend.addUser('amina@example.com', 'correct horse', 'Amina', ['parent'], language: 'fr');
  });

  test('signing in keeps the refresh token in protected storage and switches to the account language', () async {
    final secrets = MemoryStore();
    final session = testSession(backend, secrets: secrets);
    await session.restore();
    await session.signIn('amina@example.com', 'correct horse');
    expect(session.signedIn, isTrue);
    expect(session.user!.displayName, 'Amina');
    expect(session.language, 'fr');
    expect(secrets.values['refresh_token'], isNotNull);
  });

  test('a language picked on this device is kept at sign-in and saved on the account', () async {
    final session = testSession(backend);
    await session.restore();
    await session.setLanguage('ar');
    await session.signIn('amina@example.com', 'correct horse');
    expect(session.language, 'ar');
    expect(session.user!.language, 'ar');
    expect(backend.users.values.firstWhere((u) => u['email'] == 'amina@example.com')['language'], 'ar');
  });

  test('a saved sign-in is restored at the next launch', () async {
    final secrets = MemoryStore();
    final first = testSession(backend, secrets: secrets);
    await first.restore();
    await first.signIn('amina@example.com', 'correct horse');

    final next = testSession(backend, secrets: secrets);
    await next.restore();
    expect(next.signedIn, isTrue);
    expect(next.user!.email, 'amina@example.com');
  });

  test('an expired access token is renewed once, even for calls made at the same time', () async {
    final session = testSession(backend);
    await session.restore();
    await session.signIn('amina@example.com', 'correct horse');
    backend.expireAll();
    backend.refreshCalls = 0;

    final results = await Future.wait([
      session.authed(session.api.me),
      session.authed(session.api.me),
      session.authed(session.api.children),
    ]);
    expect(results, hasLength(3));
    expect(backend.refreshCalls, 1);
    expect(session.signedIn, isTrue);
  });

  test('a refresh token the server refuses signs the person out', () async {
    final secrets = MemoryStore();
    final session = testSession(backend, secrets: secrets);
    await session.restore();
    await session.signIn('amina@example.com', 'correct horse');
    backend.refreshTokens.clear();
    backend.expireAll();

    await expectLater(session.authed(session.api.me), throwsA(isA<ApiException>()));
    expect(session.signedIn, isFalse);
    expect(secrets.values['refresh_token'], isNull);
  });

  test('a child session is reopened through the parent when it expires', () async {
    final session = testSession(backend);
    await session.restore();
    await session.signIn('amina@example.com', 'correct horse');
    final created = await session.adult((t) => session.api.createChild(t, {
          'display_name': 'Yusuf',
          'language': 'ar',
          'guardian_consent': true,
        }));
    await session.openChild(Child.fromJson(created));
    expect(session.currentUser!.displayName, 'Yusuf');
    expect(session.currentUser!.isChild, isTrue);

    backend.expireAll();
    final me = await session.authed(session.api.me);
    expect(me['display_name'], 'Yusuf');

    session.closeChild();
    expect(session.currentUser!.displayName, 'Amina');
  });

  test('signing out ends the session on the server too', () async {
    final session = testSession(backend);
    await session.restore();
    await session.signIn('amina@example.com', 'correct horse');
    expect(backend.refreshTokens, hasLength(1));
    await session.signOut();
    expect(session.signedIn, isFalse);
    expect(backend.refreshTokens, isEmpty);
  });

  test('the chosen language is remembered', () async {
    final prefs = MemoryStore();
    final session = testSession(backend, prefs: prefs);
    await session.restore();
    await session.setLanguage('ar');
    final next = testSession(backend, prefs: prefs);
    await next.restore();
    expect(next.language, 'ar');
  });

  test('no network is reported as such, and keeps a saved sign-in for the next launch', () async {
    final secrets = MemoryStore()..values['refresh_token'] = 'saved';
    final offline = MockClient((_) async => throw Exception('no network'));
    final api = Api(base: Uri.parse('https://api.test/'), client: offline);
    await expectLater(api.me('x'), throwsA(isA<ApiException>().having((e) => e.code, 'code', 'network_error')));

    final session = Session(api: api, secrets: secrets, prefs: MemoryStore());
    await session.restore();
    expect(session.signedIn, isFalse);
    expect(session.restoring, isFalse);
    expect(secrets.values['refresh_token'], 'saved');
  });
}
