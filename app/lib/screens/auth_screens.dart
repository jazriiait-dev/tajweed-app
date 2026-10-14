import 'package:flutter/material.dart';

import '../api/api.dart';
import '../l10n/strings.dart';
import '../state/session_scope.dart';
import '../widgets/common.dart';

final _emailPattern = RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$');

String? _requireEmail(Strings s, String? value) {
  final email = (value ?? '').trim();
  if (email.isEmpty) return s.t('field_required');
  if (!_emailPattern.hasMatch(email)) return s.t('invalid_email');
  return null;
}

class SignInScreen extends StatefulWidget {
  const SignInScreen({super.key});

  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  final _form = GlobalKey<FormState>();
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _busy = false;
  Object? _error;

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_form.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await SessionScope.of(context).signIn(_email.text.trim(), _password.text);
      if (mounted) backToStart(context);
    } on ApiException catch (error) {
      if (mounted) setState(() => _error = error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = Strings.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(s.t('sign_in')), actions: const [LanguageMenu()]),
      body: ListView(
        padding: const EdgeInsets.all(24),
        children: [
          Narrow(
            child: Form(
              key: _form,
              child: AutofillGroup(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    TextFormField(
                      key: const Key('email'),
                      controller: _email,
                      keyboardType: TextInputType.emailAddress,
                      autofillHints: const [AutofillHints.email],
                      textDirection: TextDirection.ltr,
                      decoration: InputDecoration(labelText: s.t('email')),
                      validator: (value) => _requireEmail(s, value),
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      key: const Key('password'),
                      controller: _password,
                      obscureText: true,
                      autofillHints: const [AutofillHints.password],
                      decoration: InputDecoration(labelText: s.t('password')),
                      validator: (value) => (value ?? '').isEmpty ? s.t('field_required') : null,
                      onFieldSubmitted: (_) => _submit(),
                    ),
                    FormError(_error == null ? null : s.error(_error)),
                    const SizedBox(height: 24),
                    FilledButton(
                      key: const Key('submit'),
                      onPressed: _busy ? null : _submit,
                      child: Text(s.t('sign_in')),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class RegisterScreen extends StatefulWidget {
  const RegisterScreen({super.key});

  @override
  State<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends State<RegisterScreen> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();
  final _email = TextEditingController();
  final _password = TextEditingController();
  String _accountType = 'student';
  bool _confirmsAdult = false;
  bool _busy = false;
  String? _message;

  @override
  void dispose() {
    _name.dispose();
    _email.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final s = Strings.of(context);
    final valid = _form.currentState!.validate();
    if (!_confirmsAdult) {
      setState(() => _message = s.t('must_confirm_adult'));
      return;
    }
    if (!valid) return;
    setState(() {
      _busy = true;
      _message = null;
    });
    try {
      await SessionScope.of(context).register(
        email: _email.text.trim(),
        password: _password.text,
        displayName: _name.text.trim(),
        accountType: _accountType,
      );
      if (mounted) backToStart(context);
    } on ApiException catch (error) {
      if (mounted) setState(() => _message = s.error(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = Strings.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(s.t('create_account')), actions: const [LanguageMenu()]),
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
                    key: const Key('name'),
                    controller: _name,
                    autofillHints: const [AutofillHints.name],
                    decoration: InputDecoration(labelText: s.t('display_name')),
                    validator: (value) => (value ?? '').trim().isEmpty ? s.t('field_required') : null,
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    key: const Key('email'),
                    controller: _email,
                    keyboardType: TextInputType.emailAddress,
                    autofillHints: const [AutofillHints.email],
                    textDirection: TextDirection.ltr,
                    decoration: InputDecoration(labelText: s.t('email')),
                    validator: (value) => _requireEmail(s, value),
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    key: const Key('password'),
                    controller: _password,
                    obscureText: true,
                    autofillHints: const [AutofillHints.newPassword],
                    decoration: InputDecoration(labelText: s.t('password'), helperText: s.t('password_hint')),
                    validator: (value) => (value ?? '').length < 8 ? s.t('password_hint') : null,
                  ),
                  const SizedBox(height: 24),
                  Text(s.t('account_type'), style: Theme.of(context).textTheme.titleSmall),
                  const SizedBox(height: 8),
                  SegmentedButton<String>(
                    key: const Key('account_type'),
                    segments: [
                      ButtonSegment(value: 'student', label: Text(s.t('type_student'))),
                      ButtonSegment(value: 'parent', label: Text(s.t('type_parent'))),
                    ],
                    selected: {_accountType},
                    onSelectionChanged: (choice) => setState(() => _accountType = choice.first),
                  ),
                  const SizedBox(height: 16),
                  CheckboxListTile(
                    key: const Key('confirms_adult'),
                    contentPadding: EdgeInsets.zero,
                    controlAffinity: ListTileControlAffinity.leading,
                    value: _confirmsAdult,
                    title: Text(s.t('confirm_adult')),
                    onChanged: (value) => setState(() => _confirmsAdult = value ?? false),
                  ),
                  FormError(_message),
                  const SizedBox(height: 24),
                  FilledButton(
                    key: const Key('submit'),
                    onPressed: _busy ? null : _submit,
                    child: Text(s.t('create_account')),
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
