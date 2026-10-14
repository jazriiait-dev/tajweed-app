import 'package:flutter/material.dart';

import '../l10n/strings.dart';
import '../state/session.dart';
import '../state/session_scope.dart';

/// Loads data once, shows a spinner meanwhile, and an error with a retry button.
class Loader<T> extends StatefulWidget {
  const Loader({super.key, required this.load, required this.builder});

  final Future<T> Function() load;
  final Widget Function(BuildContext context, T data, VoidCallback reload) builder;

  @override
  State<Loader<T>> createState() => _LoaderState<T>();
}

class _LoaderState<T> extends State<Loader<T>> {
  late Future<T> _future;

  @override
  void initState() {
    super.initState();
    _future = widget.load();
  }

  void _reload() => setState(() => _future = widget.load());

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<T>(
      future: _future,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snapshot.hasError) {
          return ErrorPanel(error: snapshot.error, onRetry: _reload);
        }
        return widget.builder(context, snapshot.data as T, _reload);
      },
    );
  }
}

class ErrorPanel extends StatelessWidget {
  const ErrorPanel({super.key, required this.error, this.onRetry});

  final Object? error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final s = Strings.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.info_outline, size: 40, color: Theme.of(context).colorScheme.error),
            const SizedBox(height: 12),
            Text(s.error(error), textAlign: TextAlign.center),
            if (onRetry != null) ...[
              const SizedBox(height: 12),
              OutlinedButton(onPressed: onRetry, child: Text(s.t('retry'))),
            ],
          ],
        ),
      ),
    );
  }
}

/// The language switcher shown in the top bar of every screen.
class LanguageMenu extends StatelessWidget {
  const LanguageMenu({super.key});

  @override
  Widget build(BuildContext context) {
    final session = SessionScope.of(context);
    return PopupMenuButton<String>(
      key: const Key('language_menu'),
      icon: const Icon(Icons.translate),
      tooltip: Strings.of(context).t('choose_language'),
      onSelected: session.setLanguage,
      itemBuilder: (context) => [
        for (final code in Session.languages)
          CheckedPopupMenuItem<String>(
            key: Key('language_$code'),
            value: code,
            checked: code == session.language,
            child: Text(Strings.languageNames[code]!),
          ),
      ],
    );
  }
}

/// Shows an error message under a form.
class FormError extends StatelessWidget {
  const FormError(this.message, {super.key});

  final String? message;

  @override
  Widget build(BuildContext context) {
    if (message == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Text(
        message!,
        key: const Key('form_error'),
        style: TextStyle(color: Theme.of(context).colorScheme.error),
      ),
    );
  }
}

/// Keeps forms and lists readable on wide screens such as the web.
class Narrow extends StatelessWidget {
  const Narrow({super.key, required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.topCenter,
      child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 640), child: child),
    );
  }
}

/// Returns to the first screen, which shows the right home for who is signed in.
void backToStart(BuildContext context) {
  Navigator.of(context).popUntil((route) => route.isFirst);
}
