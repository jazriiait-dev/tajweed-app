import 'package:flutter/material.dart';

import '../api/api.dart';
import '../l10n/strings.dart';
import '../state/session_scope.dart';
import '../widgets/common.dart';

class ProfileScreen extends StatefulWidget {
  const ProfileScreen({super.key});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  final _form = GlobalKey<FormState>();
  late final TextEditingController _name;
  bool _busy = false;
  String? _message;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_nameReady) {
      _name = TextEditingController(text: SessionScope.of(context).user?.displayName ?? '');
      _nameReady = true;
    }
  }

  bool _nameReady = false;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_form.currentState!.validate()) return;
    final session = SessionScope.of(context);
    final s = Strings.of(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      await session.updateProfile(displayName: _name.text.trim());
      messenger.showSnackBar(SnackBar(content: Text(s.t('saved'))));
    } on ApiException catch (error) {
      if (mounted) setState(() => _message = s.error(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _signOut() async {
    final session = SessionScope.of(context);
    backToStart(context);
    await session.signOut();
  }

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final s = Strings.of(context);
    final user = session.user;
    if (user == null) return const SizedBox.shrink();
    return Scaffold(
      appBar: AppBar(title: Text(s.t('profile')), actions: const [LanguageMenu()]),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Narrow(
            child: Form(
              key: _form,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  if (user.email != null)
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.email_outlined),
                      title: Text(user.email!, textDirection: TextDirection.ltr),
                    ),
                  TextFormField(
                    key: const Key('profile_name'),
                    controller: _name,
                    decoration: InputDecoration(labelText: s.t('display_name')),
                    validator: (value) => (value ?? '').trim().isEmpty ? s.t('field_required') : null,
                  ),
                  FormError(_message),
                  const SizedBox(height: 16),
                  FilledButton(
                    key: const Key('save_profile'),
                    onPressed: _busy ? null : _save,
                    child: Text(s.t('save')),
                  ),
                  const SizedBox(height: 32),
                  OutlinedButton.icon(
                    key: const Key('sign_out'),
                    icon: const Icon(Icons.logout),
                    label: Text(s.t('sign_out')),
                    onPressed: _signOut,
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
