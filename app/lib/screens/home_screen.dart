import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../state/session_scope.dart';
import '../widgets/common.dart';
import 'admin_screens.dart';
import 'children_screens.dart';
import 'profile_screen.dart';
import 'quran_screens.dart';

/// The home screen once signed in. What it offers depends on the person's roles.
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final s = Strings.of(context);
    final user = session.currentUser!;
    final child = session.activeChild;

    void open(Widget screen) => Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));

    return Scaffold(
      appBar: AppBar(
        title: Text(s.t('app_name')),
        actions: [
          const LanguageMenu(),
          if (child == null)
            IconButton(
              key: const Key('open_profile'),
              icon: const Icon(Icons.account_circle_outlined),
              tooltip: s.t('profile'),
              onPressed: () => open(const ProfileScreen()),
            ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Narrow(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                if (child != null)
                  Card(
                    key: const Key('child_banner'),
                    color: Theme.of(context).colorScheme.secondaryContainer,
                    child: ListTile(
                      leading: const Icon(Icons.child_care),
                      title: Text(s.t('using_child', {'name': child.child.displayName})),
                      trailing: TextButton(
                        key: const Key('back_to_parent'),
                        onPressed: session.closeChild,
                        child: Text(s.t('back_to_my_account')),
                      ),
                    ),
                  ),
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Text(
                    s.t('greeting', {'name': user.displayName}),
                    key: const Key('greeting'),
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                ),
                _HomeCard(
                  key: const Key('home_read_quran'),
                  icon: Icons.auto_stories,
                  title: s.t('read_quran'),
                  onTap: () => open(const RiwayatScreen()),
                ),
                if (child == null && user.has('parent'))
                  _HomeCard(
                    key: const Key('home_children'),
                    icon: Icons.family_restroom,
                    title: s.t('my_children'),
                    onTap: () => open(const ChildrenScreen()),
                  ),
                if (child == null && user.has('admin'))
                  _HomeCard(
                    key: const Key('home_review'),
                    icon: Icons.fact_check_outlined,
                    title: s.t('review_text'),
                    onTap: () => open(const ReviewTextScreen()),
                  ),
                if (child == null && user.has('teacher'))
                  Card(
                    child: ListTile(
                      leading: const Icon(Icons.school_outlined),
                      title: Text(s.t('teacher_home')),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _HomeCard extends StatelessWidget {
  const _HomeCard({super.key, required this.icon, required this.title, required this.onTap});

  final IconData icon;
  final String title;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
        leading: Icon(icon, color: Theme.of(context).colorScheme.primary),
        title: Text(title, style: Theme.of(context).textTheme.titleMedium),
        trailing: const Icon(Icons.chevron_right),
        onTap: onTap,
      ),
    );
  }
}
