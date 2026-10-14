import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../widgets/common.dart';
import 'auth_screens.dart';
import 'quran_screens.dart';

/// The first screen for someone who is not signed in.
class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = Strings.of(context);
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(s.t('app_name')), actions: const [LanguageMenu()]),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Narrow(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const SizedBox(height: 24),
                Icon(Icons.menu_book_rounded, size: 72, color: theme.colorScheme.primary),
                const SizedBox(height: 24),
                Text(
                  s.t('welcome_title'),
                  key: const Key('welcome_title'),
                  textAlign: TextAlign.center,
                  style: theme.textTheme.headlineSmall,
                ),
                const SizedBox(height: 12),
                Text(s.t('welcome_body'), textAlign: TextAlign.center, style: theme.textTheme.bodyLarge),
                const SizedBox(height: 32),
                FilledButton.icon(
                  key: const Key('read_quran'),
                  icon: const Icon(Icons.auto_stories),
                  label: Text(s.t('read_quran')),
                  onPressed: () => Navigator.of(context)
                      .push(MaterialPageRoute(builder: (_) => const RiwayatScreen())),
                ),
                const SizedBox(height: 12),
                OutlinedButton(
                  key: const Key('go_sign_in'),
                  onPressed: () => Navigator.of(context)
                      .push(MaterialPageRoute(builder: (_) => const SignInScreen())),
                  child: Text(s.t('sign_in')),
                ),
                const SizedBox(height: 12),
                TextButton(
                  key: const Key('go_register'),
                  onPressed: () => Navigator.of(context)
                      .push(MaterialPageRoute(builder: (_) => const RegisterScreen())),
                  child: Text(s.t('create_account')),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
