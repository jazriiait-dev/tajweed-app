import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tajweed_app/l10n/strings.dart';
import 'package:tajweed_app/screens/quran_screens.dart';
import 'package:tajweed_app/state/stores.dart';

import 'fake_backend.dart';

void main() {
  late FakeBackend backend;

  setUp(() {
    backend = FakeBackend();
    backend.addUser('amina@example.com', 'correct horse', 'Amina', ['parent']);
    backend.addUser('admin@example.com', 'admin password', 'Admin', ['admin']);
  });

  group('Translations', () {
    test('every key exists in Arabic, English and French', () {
      final english = Strings.all['en']!.keys.toSet();
      for (final language in ['ar', 'fr']) {
        final keys = Strings.all[language]!.keys.toSet();
        expect(english.difference(keys), isEmpty, reason: 'missing in $language');
        expect(keys.difference(english), isEmpty, reason: 'extra in $language');
      }
    });

    test('placeholders are filled in', () {
      expect(Strings('fr').t('greeting', {'name': 'Amina'}), 'Assalamou alaykoum, Amina');
    });

    test('ayah numbers use Arabic-Indic digits', () {
      expect(arabicNumber(286), '٢٨٦');
      expect(ayahMarker(7), '﴿٧﴾');
    });
  });

  testWidgets('the welcome screen follows the chosen language, right to left in Arabic', (tester) async {
    final prefs = MemoryStore();
    final session = await startApp(tester, backend, prefs: prefs);
    expect(find.text('Learn, memorize and recite the Quran'), findsOneWidget);
    expect(Directionality.of(tester.element(find.byKey(const Key('welcome_title')))), TextDirection.ltr);

    await tester.tap(find.byKey(const Key('language_menu')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('language_ar')).last);
    await tester.pumpAndSettle();

    expect(find.text('تعلّم القرآن واحفظه ورتّله'), findsOneWidget);
    expect(Directionality.of(tester.element(find.byKey(const Key('welcome_title')))), TextDirection.rtl);
    expect(session.language, 'ar');
    expect(prefs.values['language'], 'ar');
  });

  testWidgets('signing in with a wrong password shows a message; the right one opens the home screen',
      (tester) async {
    await startApp(tester, backend);
    await signInAs(tester, 'amina@example.com', 'wrong password');
    expect(find.text('The email or password is not correct.'), findsOneWidget);

    await enter(tester, 'password', 'correct horse');
    await tap(tester, 'submit');
    expect(find.text('Assalamu alaykum, Amina'), findsOneWidget);
    expect(find.byKey(const Key('home_children')), findsOneWidget);
    expect(find.byKey(const Key('home_review')), findsNothing);
  });

  testWidgets('the sign-in form checks the email before calling the server', (tester) async {
    await startApp(tester, backend);
    await signInAs(tester, 'not-an-email', 'x');
    expect(find.text('Enter a valid email address'), findsOneWidget);
    expect(backend.calls.where((call) => call.startsWith('POST /auth/login')), isEmpty);
  });

  testWidgets('creating an account needs the adult confirmation', (tester) async {
    await startApp(tester, backend);
    await tap(tester, 'go_register');
    await enter(tester, 'name', 'Bilal');
    await enter(tester, 'email', 'bilal@example.com');
    await enter(tester, 'password', 'battery staple');
    await tap(tester, 'submit');
    expect(find.text('Please confirm that you are an adult.'), findsOneWidget);
    expect(backend.calls.where((call) => call.startsWith('POST /auth/register')), isEmpty);

    await tap(tester, 'confirms_adult');
    await tap(tester, 'submit');
    expect(find.text('Assalamu alaykum, Bilal'), findsOneWidget);
  });

  testWidgets('a parent adds a child with consent, opens the profile, and comes back', (tester) async {
    await startApp(tester, backend);
    await signInAs(tester, 'amina@example.com', 'correct horse');
    await tap(tester, 'home_children');
    expect(find.byKey(const Key('no_children')), findsOneWidget);

    await tap(tester, 'add_child');
    await enter(tester, 'child_name', 'Yusuf');
    await tap(tester, 'submit');
    expect(find.text('Consent is required to create a child profile.'), findsOneWidget);

    await tap(tester, 'guardian_consent');
    await tap(tester, 'submit');
    expect(find.text('Yusuf'), findsOneWidget);

    await tester.tap(find.text('Open profile'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('child_banner')), findsOneWidget);
    expect(find.text('Assalamu alaykum, Yusuf'), findsOneWidget);
    // A child profile cannot reach the parent's pages.
    expect(find.byKey(const Key('home_children')), findsNothing);
    expect(find.byKey(const Key('open_profile')), findsNothing);

    await tap(tester, 'back_to_parent');
    expect(find.text('Assalamu alaykum, Amina'), findsOneWidget);
  });

  testWidgets('the Quran can be read without an account', (tester) async {
    await startApp(tester, backend);
    await tap(tester, 'read_quran');
    expect(find.text('Hafs from Asim'), findsOneWidget);
    expect(find.text('Coming soon'), findsOneWidget); // Warsh

    await tap(tester, 'riwaya_hafs');
    expect(find.text('Al-Ikhlas · 4 ayat'), findsOneWidget);
    expect(find.text('Test source'), findsOneWidget);

    await tap(tester, 'surah_112');
    final block = tester.widget<Text>(find.byKey(const Key('ayat_block_0')));
    final shown = block.textSpan!.toPlainText();
    expect(shown, contains('placeholder 112:1'));
    expect(shown, contains('placeholder 112:4'));
    expect(shown, contains(ayahMarker(4)));
    expect(block.textDirection, TextDirection.rtl);
  });

  testWidgets('a text waiting for review is hidden from students and shown to admins with a banner',
      (tester) async {
    backend.hafsStatus = 'imported';
    await startApp(tester, backend);
    await tap(tester, 'read_quran');
    final hafs = tester.widget<ListTile>(find.byKey(const Key('riwaya_hafs')));
    expect(hafs.enabled, isFalse);
  });

  testWidgets('an admin previews and approves the text', (tester) async {
    backend.hafsStatus = 'imported';
    await startApp(tester, backend);
    await signInAs(tester, 'admin@example.com', 'admin password');
    await tap(tester, 'home_review');
    expect(find.text('Waiting for review'), findsOneWidget);

    await tap(tester, 'preview_hafs');
    expect(find.byKey(const Key('review_banner')), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();

    await tap(tester, 'approve_hafs');
    await tap(tester, 'confirm_approve');
    expect(backend.hafsStatus, 'imported', reason: 'a reviewer name is required');
    await enter(tester, 'reviewer_name', 'Shaykh Reviewer');
    await tap(tester, 'confirm_approve');
    expect(backend.hafsStatus, 'approved');
    expect(backend.reviewer, 'Shaykh Reviewer');
    expect(find.text('Reviewed by Shaykh Reviewer'), findsOneWidget);
  });

  testWidgets('signing out returns to the welcome screen', (tester) async {
    final secrets = MemoryStore();
    await startApp(tester, backend, secrets: secrets);
    await signInAs(tester, 'amina@example.com', 'correct horse');
    await tap(tester, 'open_profile');
    await tap(tester, 'sign_out');
    expect(find.byKey(const Key('welcome_title')), findsOneWidget);
    expect(secrets.values['refresh_token'], isNull);
  });
}
