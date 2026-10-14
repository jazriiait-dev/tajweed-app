import 'package:flutter/foundation.dart' show kIsWeb;

/// Where the API lives.
///
/// Set it when building:  flutter build apk --dart-define=API_URL=https://api.example.org
/// On the web, when it is not set, the app uses the address it was loaded from.
class AppConfig {
  static const String _fromBuild = String.fromEnvironment('API_URL');

  static Uri apiBase() {
    if (_fromBuild.isNotEmpty) return Uri.parse(_fromBuild);
    if (kIsWeb) return Uri.parse('${Uri.base.origin}/');
    return Uri.parse('http://localhost:8000/');
  }
}
