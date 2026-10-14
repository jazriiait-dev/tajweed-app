import 'package:flutter/material.dart';

import '../api/api.dart';
import '../api/models.dart';
import '../l10n/strings.dart';
import '../state/session.dart';
import '../state/session_scope.dart';
import '../widgets/common.dart';

class ChildrenScreen extends StatefulWidget {
  const ChildrenScreen({super.key});

  @override
  State<ChildrenScreen> createState() => _ChildrenScreenState();
}

class _ChildrenScreenState extends State<ChildrenScreen> {
  int _version = 0;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final s = Strings.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(s.t('my_children')), actions: const [LanguageMenu()]),
      floatingActionButton: FloatingActionButton.extended(
        key: const Key('add_child'),
        icon: const Icon(Icons.add),
        label: Text(s.t('add_child')),
        onPressed: () async {
          final added = await Navigator.of(context)
              .push<bool>(MaterialPageRoute(builder: (_) => const AddChildScreen()));
          if (added == true) setState(() => _version++);
        },
      ),
      body: Loader<List<Child>>(
        key: ValueKey(_version),
        load: () async => (await session.adult(session.api.children)).map(Child.fromJson).toList(),
        builder: (context, children, _) => Narrow(
          child: children.isEmpty
              ? Center(child: Text(s.t('no_children'), key: const Key('no_children')))
              : ListView(
                  padding: const EdgeInsets.only(bottom: 96),
                  children: [
                    for (final child in children)
                      ListTile(
                        key: Key('child_${child.id}'),
                        leading: CircleAvatar(child: Text(child.displayName.characters.first)),
                        title: Text(child.displayName),
                        subtitle: Text(Strings.languageNames[child.language] ?? child.language),
                        trailing: FilledButton.tonal(
                          key: Key('open_child_${child.id}'),
                          onPressed: () => _open(context, child),
                          child: Text(s.t('open_profile')),
                        ),
                      ),
                  ],
                ),
        ),
      ),
    );
  }

  Future<void> _open(BuildContext context, Child child) async {
    final session = SessionScope.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final s = Strings.of(context);
    try {
      await session.openChild(child);
      if (context.mounted) backToStart(context);
    } on ApiException catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(s.error(error))));
    }
  }
}

class AddChildScreen extends StatefulWidget {
  const AddChildScreen({super.key});

  @override
  State<AddChildScreen> createState() => _AddChildScreenState();
}

class _AddChildScreenState extends State<AddChildScreen> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  String? _language;
  bool _consent = false;
  bool _busy = false;
  String? _message;

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final session = SessionScope.of(context);
    final s = Strings.of(context);
    final valid = _form.currentState!.validate();
    if (!_consent) {
      setState(() => _message = s.t('must_consent'));
      return;
    }
    if (!valid) return;
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      await session.adult((token) => session.api.createChild(token, {
            'display_name': _name.text.trim(),
            'language': _language ?? session.language,
            'guardian_consent': true,
          }));
      if (mounted) Navigator.of(context).pop(true);
    } on ApiException catch (error) {
      if (mounted) setState(() => _message = s.error(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final s = Strings.of(context);
    final language = _language ?? session.language;
    return Scaffold(
      appBar: AppBar(title: Text(s.t('add_child'))),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Narrow(
            child: Form(
              key: _form,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  TextFormField(
                    key: const Key('child_name'),
                    controller: _name,
                    decoration: InputDecoration(labelText: s.t('child_name')),
                    validator: (value) => (value ?? '').trim().isEmpty ? s.t('field_required') : null,
                  ),
                  const SizedBox(height: 24),
                  Text(s.t('child_language'), style: Theme.of(context).textTheme.titleSmall),
                  const SizedBox(height: 8),
                  SegmentedButton<String>(
                    key: const Key('child_language'),
                    segments: [
                      for (final code in Session.languages)
                        ButtonSegment(value: code, label: Text(Strings.languageNames[code]!)),
                    ],
                    selected: {language},
                    onSelectionChanged: (choice) => setState(() => _language = choice.first),
                  ),
                  const SizedBox(height: 16),
                  CheckboxListTile(
                    key: const Key('guardian_consent'),
                    contentPadding: EdgeInsets.zero,
                    controlAffinity: ListTileControlAffinity.leading,
                    value: _consent,
                    title: Text(s.t('guardian_consent')),
                    onChanged: (value) => setState(() => _consent = value ?? false),
                  ),
                  FormError(_message),
                  const SizedBox(height: 24),
                  FilledButton(
                    key: const Key('submit'),
                    onPressed: _busy ? null : _submit,
                    child: Text(s.t('add_child')),
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
