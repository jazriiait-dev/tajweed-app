/// The shapes the app reads from the API.
library;

class User {
  User({
    required this.id,
    required this.displayName,
    required this.language,
    required this.roles,
    required this.isChild,
    this.email,
  });

  factory User.fromJson(Map<String, dynamic> json) => User(
        id: json['id'] as String,
        displayName: json['display_name'] as String,
        email: json['email'] as String?,
        language: (json['language'] as String?) ?? 'ar',
        roles: ((json['roles'] as List?) ?? const []).map((role) => role.toString()).toList(),
        isChild: (json['is_child'] as bool?) ?? false,
      );

  final String id;
  final String displayName;
  final String? email;
  final String language;
  final List<String> roles;
  final bool isChild;

  bool has(String role) => roles.contains(role);
}

class Child {
  Child({required this.id, required this.displayName, required this.language});

  factory Child.fromJson(Map<String, dynamic> json) => Child(
        id: json['id'] as String,
        displayName: json['display_name'] as String,
        language: (json['language'] as String?) ?? 'ar',
      );

  final String id;
  final String displayName;
  final String language;
}

class Riwaya {
  Riwaya({
    required this.code,
    required this.names,
    required this.available,
    this.status,
    this.ayahCount,
    this.reviewerName,
  });

  factory Riwaya.fromJson(Map<String, dynamic> json) => Riwaya(
        code: json['code'] as String,
        names: ((json['name'] as Map?) ?? const {}).map((key, value) => MapEntry('$key', '$value')),
        available: (json['available'] as bool?) ?? false,
        status: json['status'] as String?,
        ayahCount: json['ayah_count'] as int?,
        reviewerName: json['reviewer_name'] as String?,
      );

  final String code;
  final Map<String, String> names;
  final bool available;

  // Only sent to admins.
  final String? status;
  final int? ayahCount;
  final String? reviewerName;

  String nameIn(String language) => names[language] ?? names['en'] ?? code;

  /// Admins may open a text that is imported but not yet approved, to check it.
  bool canOpen({required bool isAdmin}) => available || (isAdmin && status == 'imported');
}

class SurahSummary {
  SurahSummary({required this.number, required this.nameAr, required this.nameLatin, required this.ayahCount});

  factory SurahSummary.fromJson(Map<String, dynamic> json) => SurahSummary(
        number: json['number'] as int,
        nameAr: json['name_ar'] as String,
        nameLatin: json['name_latin'] as String,
        ayahCount: json['ayah_count'] as int,
      );

  final int number;
  final String nameAr;
  final String nameLatin;
  final int ayahCount;
}

class SurahList {
  SurahList({required this.approved, required this.surahs, this.textSource, this.textNotice});

  factory SurahList.fromJson(Map<String, dynamic> json) => SurahList(
        approved: (json['approved'] as bool?) ?? false,
        textSource: json['text_source'] as String?,
        textNotice: json['text_notice'] as String?,
        surahs: ((json['surahs'] as List?) ?? const [])
            .map((item) => SurahSummary.fromJson((item as Map).cast<String, dynamic>()))
            .toList(),
      );

  final bool approved;
  final String? textSource;
  final String? textNotice;
  final List<SurahSummary> surahs;
}

class Ayah {
  Ayah(this.number, this.text);

  final int number;
  final String text;
}

class SurahText {
  SurahText({
    required this.number,
    required this.nameAr,
    required this.nameLatin,
    required this.ayahCount,
    required this.approved,
    required this.ayahs,
  });

  factory SurahText.fromJson(Map<String, dynamic> json) => SurahText(
        number: json['number'] as int,
        nameAr: json['name_ar'] as String,
        nameLatin: json['name_latin'] as String,
        ayahCount: json['ayah_count'] as int,
        approved: (json['approved'] as bool?) ?? false,
        ayahs: ((json['ayahs'] as List?) ?? const []).map((item) {
          final ayah = (item as Map).cast<String, dynamic>();
          // The text is shown exactly as stored; never altered.
          return Ayah(ayah['number'] as int, ayah['text'] as String);
        }).toList(),
      );

  final int number;
  final String nameAr;
  final String nameLatin;
  final int ayahCount;
  final bool approved;
  final List<Ayah> ayahs;
}
