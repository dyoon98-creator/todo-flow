# todo-flow 운영 설명 만화 — 2026-09-26

## 구성·coverage

Main 지시에 따라 일반 운영 흐름 다음에 local manual-orca 흐름을 두 페이지로 나눴다. 실행·검증·provider 작업을 수행한 것으로 그리지 않았다.

| 페이지 | 패널 | 주요 학습 내용 |
|---|---:|---|
| 1/2 | 8 | 도구와 업무 대상 구분, 연결 전 권한 확인, 등록·추천·선택의 구분, 실제 track ID와 현재 worker/policy 확인, 파일 정본과 SQLite cache, 같은 SHA 검수/독립 리뷰, land 권한과 외부 효과 검증, 기존 상태로 질문·재개 |
| 2/2 | 8 | source/skill manifest 고정, validation·backup 뒤 claim, 이후 Main이 dispatch, provider record·startup prompt·exit·report 결속, staged output 검증, binding 후 단일 Store transaction, PID/창/exit만으로 완료 판정 금지, docs local-only |

## PNG와 최종 시각검토

| 페이지 | SHA-256 | px | X1 사실 | X2 source 연결 | X3 한글 | X4 만화 |
|---|---|---|---|---|---|---|
| 1/2 | `65cb0b938df15790ecfbd0352e279da8227ae659a919c53ff9ba66261ecef5f0` | 1024×1536 | PASS | PASS | PASS | PASS |
| 2/2 | `397036dd94ce84fb8702edaf79754f8515729cefa525ba5bffc86867ec117b16` | 1024×1536 | PASS | PASS | PASS | PASS |

최종 저장본 두 장을 원본 해상도로 검토. 페이지 1에서 발명된 SHA sample을 지웠고, 외부 효과 확인 문구를 중립적으로 바꿨다. 실제 프로세스가 끝난 것처럼 표시하지 않았다.

## source snapshot SHA-256

| 파일 | SHA-256 |
|---|---|
| 입력 `docs/운영가이드.md` | `bc64ace7599bbf34b04a271d6c2dc073dc844c56977133cb05f74b77b579a552` |
| `OPERATIONS.md` | `4ba671a862961a63b4fb44e4c63f0128462120e45e60ff83c184891d2b0a9f5a` |
| `AGENTS.md` | `170b2a9e80b5776f91d959c4a1cdee091b7206e859ad3d37fe3ee3c96f034de6` |
| `docs/운영가이드.d/시작과연결.md` | `ad1167377a21305072a9751dae96cb58009b3b63191af73b10eb73fb2646ddc8` |
| `docs/운영가이드.d/등록선택실행.md` | `1afe5694b664dd37b7712568efd94869e36047698c275a2a5c80ddd1c60c13cd` |
| `docs/운영가이드.d/검수와후속.md` | `0012944c540b1043f82b82645aa915e8d2df88b3edfa97daa3c8756da334cbf0` |
| `docs/운영가이드.d/중단과복구.md` | `b556c3bdb506b002f85a82686f9ea0b2094d1ae24dd12207d6c9adbf91cbb85f` |
| `docs/운영가이드.d/manual-orca.md` | `7d5f61f5282c1cf19b54007adf891cbf6be56b572b46f38a3f8503218dd35c40` |
| `src/todo_flow/manual_orca.py` | `85e3ae5cace58d1e5a73c7c712a1c3e7e06e4a203938930793168cb51258d80f` |

## 링크와 보관 경계

Local docs guide의 refer 표에 전체 2페이지 링크를 추가했다. 입력 guide SHA `bc64ace7599bbf34b04a271d6c2dc073dc844c56977133cb05f74b77b579a552`, 링크 후 SHA `3c2712cfaf3493feaf0266d15e37dffd8b8e05f24cf68fbc8c6cb080d894a909`. `docs/`는 local-only·Git ignored 상태로 뒀고 ignore/force-add는 건드리지 않았다.

(2026-09-27 갱신: 루트의 운영가이드·상세·만화 PNG·이 companion 문서는 사용자 지시에 따라 공개 추적으로 옮겨졌다. `docs/`의 compat symlink와 나머지 로컬 기록은 계속 Git ignored다.)

Prompt·수정 이력은 `comic-prompt-20260926.md`에 기록했다.
