import 'package:flutter/widgets.dart';

import 'session.dart';

/// Makes the [Session] available to every screen, and rebuilds them when it changes.
class SessionScope extends InheritedNotifier<Session> {
  const SessionScope({super.key, required Session session, required super.child})
      : super(notifier: session);

  static Session of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<SessionScope>();
    assert(scope != null, 'No SessionScope above this widget.');
    return scope!.notifier!;
  }
}
