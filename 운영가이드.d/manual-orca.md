# 수동 Orca 연결의 현재 계약

[운영가이드](../운영가이드.md) · [정확한 명령과 경계](../OPERATIONS.md#local-extension-manually-supervised-orca-result-import)

**`python -m todo_flow.manual_orca`는 로컬 확장이다.** 일반 `trackrun`이나 upstream CLI와 동일시하지 않는다. 정본은 [OPERATIONS.md](../OPERATIONS.md)의 Manual Orca 절과 [구현](../src/todo_flow/manual_orca.py)이다.

1. source·skill manifest를 고정한 뒤 `prepare`로 백업하고 TODO work request를 먼저 claim한다.
2. Main이 실제 Orca 정책 dispatch를 수행한다. prepare 자체는 Engine이나 trackrun을 시작하지 않는다.
3. 실제 runtime 종료 뒤 `bind-completion`으로 정확한 global-dispatch·provider-bridge·startup prompt hash·process exit·report hash를 결속한다.
4. `import-result`가 현재 request·source·skill·staged output 해시를 다시 확인한다. 일치하면 task 완료와 track pause를 한 Store transaction으로 기록한다.

요청 결속 없는 native 실행 결과를 사후 TODO 완료로 붙이지 않는다. 변경된 source, 미완료 runtime, 지원하지 않는 effect, stale report는 미완료로 남긴다. 시작 receipt와 작업 성공을 혼동하거나 `DELIVERED` 증거를 만들어 내지 않는다.

이 설명은 현재 소스 계약 확인이다. 실제 업무 실행·설치·import 성공은 이번 문서 갱신에서 검증하지 않았다.
