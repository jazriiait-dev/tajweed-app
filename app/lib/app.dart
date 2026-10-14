import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';

import 'l10n/strings.dart';
import 'screens/home_screen.dart';
import 'screens/welcome_screen.dart';
import 'state/session.dart';
import 'state/session_scope.dart';

class TajweedApp extends StatelessWidget {
  const TajweedApp({super.key, required this.session});

  final Session session;

  @override
  Widget build(BuildContext context) {
    return SessionScope(
      session: session,
      child: Builder(builder: (context) {
        final session = SessionScope.of(context);
        final Widget home;
        if (session.restoring) {
          home = const Scaffold(body: Center(child: CircularProgressIndicator()));
        } else if (session.signedIn) {
          home = const HomeScreen();
        } else {
          home = const WelcomeScreen();
        }
        return MaterialApp(
          title: Strings(session.language).t('app_name'),
          debugShowCheckedModeBanner: false,
          locale: Locale(session.language),
          supportedLocales: [for (final code in Session.languages) Locale(code)],
          localizationsDelegates: const [
            GlobalMaterialLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
          ],
          theme: buildTheme(session.language, Brightness.light),
          darkTheme: buildTheme(session.language, Brightness.dark),
          home: home,
        );
      }),
    );
  }
}

ThemeData buildTheme(String language, Brightness brightness) {
  return ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xFF1F6F5C), brightness: brightness),
    // Latin letters and digits use Noto Sans; Noto Sans has no Arabic letters,
    // so Arabic interface text falls back to Noto Naskh Arabic. Mixed text,
    // such as an email address on an Arabic screen, gets the right font for each.
    fontFamily: 'NotoSans',
    fontFamilyFallback: const ['NotoNaskhArabic'],
  );
}
