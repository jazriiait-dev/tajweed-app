import 'dart:async';
import 'dart:ui' show PlatformDispatcher;

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import 'api/api.dart';
import 'app.dart';
import 'config.dart';
import 'state/session.dart';
import 'state/stores.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  // The fonts are free under the SIL Open Font License, which asks that the
  // licence travels with them. It appears on the app's licences page.
  LicenseRegistry.addLicense(() async* {
    for (final font in const ['AmiriQuran', 'NotoNaskhArabic', 'NotoSans']) {
      yield LicenseEntryWithLineBreaks([font], await rootBundle.loadString('assets/fonts/OFL-$font.txt'));
    }
  });

  final device = PlatformDispatcher.instance.locale.languageCode;
  final session = Session(
    api: Api(base: AppConfig.apiBase()),
    secrets: SecureStore(),
    prefs: PrefsStore(),
    initialLanguage: Session.languages.contains(device) ? device : 'en',
  );
  runApp(TajweedApp(session: session));
  unawaited(session.restore());
}
