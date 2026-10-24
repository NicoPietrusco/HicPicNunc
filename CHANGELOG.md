# Changelog

## [0.4.1](https://github.com/NicoPietrusco/HicPicNunc/compare/v0.4.0...v0.4.1) (2026-10-24)


### Bug Fixes

* get new Picker download links when they expire ([#95](https://github.com/NicoPietrusco/HicPicNunc/issues/95)) ([d8e9657](https://github.com/NicoPietrusco/HicPicNunc/commit/d8e9657526b57d5a76c1311c639d1bb5d4269dd5))
* restore dates on large folders by uploading in chunks ([#93](https://github.com/NicoPietrusco/HicPicNunc/issues/93)) ([72ddd58](https://github.com/NicoPietrusco/HicPicNunc/commit/72ddd58371baaab13ed2719ce54ebd72a5710ae9))

## [0.4.0](https://github.com/NicoPietrusco/HicPicNunc/compare/v0.3.0...v0.4.0) (2026-10-18)


### Features

* **i18n:** translate the interface into Italian ([#73](https://github.com/NicoPietrusco/HicPicNunc/issues/73)) ([0de4481](https://github.com/NicoPietrusco/HicPicNunc/commit/0de4481c6550778dd63242890dbc33ebf02e59a0))
* **oauth:** add openid and email scopes with account chooser and revocation ([2a7e11b](https://github.com/NicoPietrusco/HicPicNunc/commit/2a7e11b162fe7d2e6302d78b7af40e821cea5408))
* **web:** add sign-out endpoint, identity display, and UI controls ([649545a](https://github.com/NicoPietrusco/HicPicNunc/commit/649545a20263da3579188d9f981f01f13fb60215))


### Bug Fixes

* address PR review comments for sign-out and account switcher ([fd27d6c](https://github.com/NicoPietrusco/HicPicNunc/commit/fd27d6c8635c845c895056ccc9655c7c6b6f5945))
* date exported files in the photo's own time zone ([10bf698](https://github.com/NicoPietrusco/HicPicNunc/commit/10bf698b32d1613137a6676511413366c52d81b8))
* handle granular consent and enforce Google Photos scope grant ([8d15b6d](https://github.com/NicoPietrusco/HicPicNunc/commit/8d15b6d6a69014a54dc8b0fa5337209c0cec52d8))
* keep cryptography 48 on Intel macOS so the app starts ([2a063be](https://github.com/NicoPietrusco/HicPicNunc/commit/2a063bec9748596428797b2263f3b390c7b96036))
* keep the color profile of re-encoded WebP copies ([be2e691](https://github.com/NicoPietrusco/HicPicNunc/commit/be2e691f735b69ae5be72f01f7e28a2f52bdbbd9))
* keep the original file names in exports ([#80](https://github.com/NicoPietrusco/HicPicNunc/issues/80)) ([c66f26f](https://github.com/NicoPietrusco/HicPicNunc/commit/c66f26f839e9c21ae0cb824209d6cd857f724e42))
