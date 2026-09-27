# ImageGen prompt record — todo-flow — 2026-09-26

외부 생성은 비식별 작업본과 이 파일의 프롬프트만 사용. 실제 계정 주소·사용자 원문·인증값 미포함.

## 01 — initial generation

```text
Use case: illustration-story
Asset type: todo-flow operating-guide comic PNG, page 1 of 2. Image 1 is a style reference only: white background, clean black line art, blue accents, adult operator and friendly small guide robot, clear numbered panels. Do not copy its email scenes or text.
Primary request: Make an eight-panel Korean explainer for normal todo-flow operation, from connecting a target project to reviewing and following up. Clearly separate the todo-flow tool from the target project.
Text (verbatim; no extra small text):
Title: “todo-flow — 요구 등록부터 검수와 후속 작업까지”
Page marker: “1/2”
1. “개발 요구 → 실행·검증·독립 리뷰·후속 확인”; label separate boxes “todo-flow 도구” and “업무 대상 프로젝트”
2. “처음 연결: 프로젝트·상태 경로·권한 확인”; “과거 설치 기록 ≠ 현재 성공”
3. “요구 등록 → 추천 검토 → 사용자가 선택”; keep all three states separate
4. “선택한 실제 트랙 ID로 trackrun”; “워커 어댑터·실행 정책 확인”
5. “정본은 파일”; “SQLite는 조회 캐시”; “중단 시 같은 상태 경로의 claim·attempt·결과 보존”
6. “후보 SHA가 같은 검증 + 독립 리뷰”; “리뷰는 commit·push·PR 게시 가능”
7. “land에는 별도 병합 권한”; “실제 외부 반영 확인”; “범위 안 결함을 TODO·Watch로 미뤄 완료 처리 금지”
8. “질문·멈춤·재개는 기존 상태에 연결”; “정책 Orca 결과는 다음 페이지”
Constraints: do not imply a worker starts automatically, do not invent track IDs or project names, do not mark installed/runtime success, no credentials or watermark. All eight panels distinct, numbered, portrait, exact Korean legible.
```

## 01 — localized edit

```text
Use case: illustration-story
Asset type: targeted edit of todo-flow comic page 1/2.
Primary request: Fix two unsupported visual claims. In panel 6, remove the invented sample text “abc123...” and its green pass mark; replace the sample hash with neutral gray placeholder bars and show a magnifier inspecting evidence, without implying a pass. Keep the panel label “후보 SHA가 같은 검증 + 독립 리뷰”. In panel 7, replace the green check beside “실제 외부 반영 확인” with an empty checkbox or magnifier; change that caption to the exact text “실제 외부 반영 여부 확인”.
Constraints: preserve all other panels, text, characters, colors, page layout, and style exactly. Do not add a hash value, commit/PR record, successful merge, project name, credential, or watermark.
```

## 02 — initial generation

```text
Use case: illustration-story
Asset type: todo-flow operating-guide comic PNG, page 2 of 2. Image 1 is a style reference only: white background, clean black line art, blue accents, adult operator and friendly small guide robot, clear numbered panels. Do not copy its email scenes or text.
Primary request: Make an eight-panel Korean explainer of the manual-orca path: Main prepares and claims; Main then runs the separately authorized Orca dispatch; only bound and revalidated evidence can be imported.
Text (verbatim; no extra small text):
Title: “todo-flow — 요청을 claim하고 검증된 Orca 결과만 가져오기”
Page marker: “2/2”
1. “작업 대상 선택 → 실행·검증·독립 리뷰”; show no worker running
2. “공용 entrypoint와 작업 refer”; “로컬 docs는 Git ignored·패키지 미포함”
3. “Main이 고정 source·skill manifest 검증”; “state 백업 후 TODO claim”; “request 경로·hash 반환”
4. “claim 뒤 Main이 request·attempt ID·hash를 넣어 Orca dispatch”; “prepare는 실행하지 않음”
5. “provider 종료 뒤 Main이 exact record·prompt hash·exit·report hash를 같은 request에 결속”
6. “import-result가 현재 request·source·skill manifest·4개 staged output hash·source claims 재검증”; “불일치면 fail closed”
7. “모든 binding 일치 후 한 transaction에서만 task 완료·track paused”; “PID·창·종료 코드만으로 완료 아님”
8. “public OPERATIONS와 local extension 계약 확인”; “ignored docs를 force-add하지 않음”
Constraints: Main owns the Orca dispatch; do not show automatic execution. Do not present PID, window, exit code, receipt, or worker label alone as completion. No invented IDs, credentials, project names, or watermark. All eight panels distinct, numbered, portrait, exact Korean legible.
```

