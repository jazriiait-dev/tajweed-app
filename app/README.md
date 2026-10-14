# The app (iOS, Android and web)

Built with Flutter. Every change is analyzed, tested and built by GitHub
(see `.github/workflows/app.yml`); the reports and a web build are published
to the `ci-output` branch.

Run it on a computer with Flutter installed:

```sh
flutter pub get
flutter test
flutter run --dart-define=API_URL=http://localhost:8000
```

On the web, when `API_URL` is not set, the app calls the API at the address
it was loaded from.

Fonts: Amiri Quran (Quran text), Noto Naskh Arabic and Noto Sans (interface),
all under the SIL Open Font License; the licences are in `assets/fonts/`.
