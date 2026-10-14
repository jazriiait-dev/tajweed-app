import 'package:flutter/material.dart';

import '../api/api.dart';
import '../api/models.dart';
import '../l10n/strings.dart';
import '../state/session_scope.dart';
import '../widgets/common.dart';
import 'quran_screens.dart';

/// Lets an admin check an imported Quran text and record the reviewer's approval.
class ReviewTextScreen extends StatelessWidget {
  const ReviewTextScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final s = Strings.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(s.t('review_text')), actions: const [LanguageMenu()]),
      body: Loader<List<Riwaya>>(
        load: () async =>
            (await session.adult((token) => session.api.riwayat(token))).map(Riwaya.fromJson).toList(),
        builder: (context, riwayat, reload) => Narrow(
          child: ListView(
            padding: const EdgeInsets.all(12),
            children: [
              for (final riwaya in riwayat)
                Card(
                  key: Key('review_${riwaya.code}'),
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(riwaya.nameIn(s.language), style: Theme.of(context).textTheme.titleMedium),
                        const SizedBox(height: 4),
                        Text(s.t('status_${riwaya.status ?? 'empty'}')),
                        if (riwaya.reviewerName != null)
                          Text(s.t('reviewed_by', {'name': riwaya.reviewerName!})),
                        if (riwaya.status == 'imported') ...[
                          const SizedBox(height: 12),
                          Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: [
                              OutlinedButton(
                                key: Key('preview_${riwaya.code}'),
                                onPressed: () => Navigator.of(context).push(
                                  MaterialPageRoute(builder: (_) => SurahListScreen(riwaya: riwaya)),
                                ),
                                child: Text(s.t('preview')),
                              ),
                              FilledButton(
                                key: Key('approve_${riwaya.code}'),
                                onPressed: () => _approve(context, riwaya, reload),
                                child: Text(s.t('approve')),
                              ),
                            ],
                          ),
                        ],
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _approve(BuildContext context, Riwaya riwaya, VoidCallback reload) async {
    final session = SessionScope.of(context);
    final s = Strings.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final reviewer = await showDialog<String>(context: context, builder: (_) => const _ApproveDialog());
    if (reviewer == null) return;
    try {
      await session.adult((token) => session.api.approveRiwaya(token, riwaya.code, reviewer));
      messenger.showSnackBar(SnackBar(content: Text(s.t('approved_done'))));
      reload();
    } on ApiException catch (error) {
      messenger.showSnackBar(SnackBar(content: Text(s.error(error))));
    }
  }
}

class _ApproveDialog extends StatefulWidget {
  const _ApproveDialog();

  @override
  State<_ApproveDialog> createState() => _ApproveDialogState();
}

class _ApproveDialogState extends State<_ApproveDialog> {
  final _form = GlobalKey<FormState>();
  final _name = TextEditingController();

  @override
  void dispose() {
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = Strings.of(context);
    return AlertDialog(
      title: Text(s.t('approve')),
      content: Form(
        key: _form,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(s.t('approve_explain')),
            const SizedBox(height: 16),
            TextFormField(
              key: const Key('reviewer_name'),
              controller: _name,
              decoration: InputDecoration(labelText: s.t('reviewer_name')),
              validator: (value) => (value ?? '').trim().length < 2 ? s.t('field_required') : null,
            ),
          ],
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.of(context).pop(), child: Text(s.t('cancel'))),
        FilledButton(
          key: const Key('confirm_approve'),
          onPressed: () {
            if (_form.currentState!.validate()) Navigator.of(context).pop(_name.text.trim());
          },
          child: Text(s.t('approve')),
        ),
      ],
    );
  }
}
