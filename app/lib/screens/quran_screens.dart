import 'package:flutter/material.dart';

import '../api/models.dart';
import '../l10n/strings.dart';
import '../state/session_scope.dart';
import '../widgets/common.dart';

const _quranFont = 'AmiriQuran';
const _arabicDigits = ['٠', '١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩'];

/// Writes a number with Arabic-Indic digits, as in the mushaf.
String arabicNumber(int number) =>
    number.toString().split('').map((digit) => _arabicDigits[int.parse(digit)]).join();

/// The end-of-ayah marker shown after each ayah: ﴿n﴾.
String ayahMarker(int number) => '﴿${arabicNumber(number)}﴾';

class RiwayatScreen extends StatelessWidget {
  const RiwayatScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final s = Strings.of(context);
    final isAdmin = session.has('admin');
    return Scaffold(
      appBar: AppBar(title: Text(s.t('choose_riwaya')), actions: const [LanguageMenu()]),
      body: Loader<List<Riwaya>>(
        load: () async => (await session.maybeAuthed((token) => session.api.riwayat(token)))
            .map(Riwaya.fromJson)
            .toList(),
        builder: (context, riwayat, _) => Narrow(
          child: ListView(
            children: [
              for (final riwaya in riwayat)
                ListTile(
                  key: Key('riwaya_${riwaya.code}'),
                  leading: const Icon(Icons.menu_book_outlined),
                  title: Text(riwaya.nameIn(s.language)),
                  subtitle: riwaya.available ? null : Text(s.t('coming_soon')),
                  enabled: riwaya.canOpen(isAdmin: isAdmin),
                  trailing: riwaya.canOpen(isAdmin: isAdmin) ? const Icon(Icons.chevron_right) : null,
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => SurahListScreen(riwaya: riwaya)),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class SurahListScreen extends StatelessWidget {
  const SurahListScreen({super.key, required this.riwaya});

  final Riwaya riwaya;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final s = Strings.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(riwaya.nameIn(s.language)), actions: const [LanguageMenu()]),
      body: Loader<SurahList>(
        load: () async =>
            SurahList.fromJson(await session.maybeAuthed((token) => session.api.surahs(token, riwaya.code))),
        builder: (context, list, _) => Narrow(
          child: ListView(
            children: [
              if (!list.approved) const _ReviewBanner(),
              for (final surah in list.surahs)
                ListTile(
                  key: Key('surah_${surah.number}'),
                  leading: CircleAvatar(child: Text('${surah.number}')),
                  title: Text(surah.nameAr, textDirection: TextDirection.rtl, style: const TextStyle(fontSize: 20)),
                  // The Latin name helps English and French readers; in Arabic it is left out.
                  subtitle: Text(s.language == 'ar'
                      ? s.t('ayah_count', {'n': '${surah.ayahCount}'})
                      : '${surah.nameLatin} · ${s.t('ayah_count', {'n': '${surah.ayahCount}'})}'),
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => SurahScreen(riwaya: riwaya, summary: surah)),
                  ),
                ),
              _SourceNotice(source: list.textSource, notice: list.textNotice),
            ],
          ),
        ),
      ),
    );
  }
}

class SurahScreen extends StatelessWidget {
  const SurahScreen({super.key, required this.riwaya, required this.summary});

  final Riwaya riwaya;
  final SurahSummary summary;

  /// Ayat are laid out in groups, so long surahs scroll smoothly.
  static const _ayatPerBlock = 15;

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    final theme = Theme.of(context);
    final textStyle = TextStyle(fontFamily: _quranFont, fontSize: 28, height: 2.1, color: theme.colorScheme.onSurface);
    final markerStyle = textStyle.copyWith(color: theme.colorScheme.primary);
    return Scaffold(
      appBar: AppBar(
        title: Text(summary.nameAr, textDirection: TextDirection.rtl),
        actions: const [LanguageMenu()],
      ),
      body: Loader<SurahText>(
        load: () async => SurahText.fromJson(
            await session.maybeAuthed((token) => session.api.surah(token, riwaya.code, summary.number))),
        builder: (context, surah, _) {
          final blocks = <List<Ayah>>[];
          for (var i = 0; i < surah.ayahs.length; i += _ayatPerBlock) {
            final end = i + _ayatPerBlock < surah.ayahs.length ? i + _ayatPerBlock : surah.ayahs.length;
            blocks.add(surah.ayahs.sublist(i, end));
          }
          final offset = surah.approved ? 0 : 1;
          return Narrow(
            child: ListView.builder(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
              itemCount: blocks.length + offset,
              itemBuilder: (context, index) {
                if (index < offset) return const _ReviewBanner();
                final block = blocks[index - offset];
                return Text.rich(
                  TextSpan(children: [
                    for (final ayah in block) ...[
                      TextSpan(text: ayah.text, style: textStyle),
                      TextSpan(text: ' ${ayahMarker(ayah.number)} ', style: markerStyle),
                    ],
                  ]),
                  key: Key('ayat_block_${index - offset}'),
                  textDirection: TextDirection.rtl,
                  textAlign: TextAlign.justify,
                );
              },
            ),
          );
        },
      ),
    );
  }
}

class _ReviewBanner extends StatelessWidget {
  const _ReviewBanner();

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      key: const Key('review_banner'),
      color: theme.colorScheme.tertiaryContainer,
      margin: const EdgeInsets.all(12),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Text(Strings.of(context).t('waiting_review')),
      ),
    );
  }
}

/// Names the source of the text, as its publisher asks.
class _SourceNotice extends StatelessWidget {
  const _SourceNotice({this.source, this.notice});

  final String? source;
  final String? notice;

  @override
  Widget build(BuildContext context) {
    if ((source ?? '').isEmpty && (notice ?? '').isEmpty) return const SizedBox.shrink();
    final small = Theme.of(context).textTheme.bodySmall;
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(Strings.of(context).t('text_source'), style: Theme.of(context).textTheme.titleSmall),
          if ((source ?? '').isNotEmpty) Text(source!, style: small),
          if ((notice ?? '').isNotEmpty) Text(notice!, style: small, textDirection: TextDirection.ltr),
        ],
      ),
    );
  }
}
