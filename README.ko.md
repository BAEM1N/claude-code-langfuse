# langfuse-claude-code

[English](README.md) | [한국어](README.ko.md)

[Claude Code](https://docs.anthropic.com/en/docs/claude-code)를 위한 자동 [Langfuse](https://langfuse.com) 트레이싱. 대화 턴, 도구 호출, 모델 응답이 Langfuse 대시보드에 구조화된 트레이스로 자동 기록됩니다. 코드 변경 없이 사용할 수 있습니다.

## 상태 (2026년 2월 25일)

- ✅ 실제 Claude Code 실행 기준 훅 파이프라인 검증 완료
- ✅ 턴 트레이스, 도구 스팬, 토큰 사용량이 Langfuse에 정상 기록됨
- ✅ 저장소 정리 완료 (불필요 추적 파일 없음 확인)
- ✅ 최종 문서 동기화 기준 `v0.0.1` 릴리즈/태그 정리 완료
- ✅ 다음 연동 저장소와 정렬 완료:
  - `langfuse-oh-my-codex`
  - `langfuse-gemini-cli`
  - `langfuse-opencode`
- 진행 문서: [English](./PROGRESS.md) | [한국어](./PROGRESS.ko.md)

## 주요 기능

- **전체 이벤트 커버리지** -- Claude Code의 4개 hook 이벤트 전체 캡처 (Stop, Notification, PreToolUse, PostToolUse)
- **턴 단위 트레이싱** -- 사용자 프롬프트 + 어시스턴트 응답이 하나의 Langfuse 트레이스로 기록
- **실시간 도구 이벤트** -- PreToolUse/PostToolUse 훅이 도구 호출을 실시간으로 정확한 타이밍과 함께 캡처
- **시스템 프롬프트 캡처** -- 시스템 메시지가 별도 스팬으로 기록
- **전체 어시스턴트 콘텐츠** -- 도구 호출 사이의 모든 텍스트 블록이 순서대로 보존 (누락 없음)
- **Thinking 블록** -- Claude의 내부 추론(`thinking`)이 별도 스팬으로 캡처
- **도구 호출 추적** -- 모든 도구 사용(Read, Write, Bash 등)의 입출력 캡처
- **토큰 사용량** -- 입출력/캐시 토큰 수가 generation에 기록
- **Stop reason** -- `end_turn`, `tool_use` 등이 메타데이터에 추적
- **세션 그룹핑** -- Claude Code 세션 ID 기준으로 트레이스 그룹화
- **증분 처리** -- 새로운 트랜스크립트 항목만 전송 (중복 없음)
- **미완성 턴 캡처** -- 응답 전에 세션이 종료되어도 사용자 메시지가 기록됨
- **Fail-open 설계** -- 오류 발생 시 훅이 조용히 종료; Claude Code 작업에 영향 없음
- **크로스 플랫폼** -- macOS, Linux, Windows 모두 지원
- **SDK 호환** -- langfuse `>= 3.12` (중첩 스팬)과 이전 버전(플랫 트레이스) 모두 지원

## 사전 요구 사항

- **Claude Code** -- 설치 및 실행 가능 상태 ([설치 가이드](https://docs.anthropic.com/en/docs/claude-code))
- **Python 3.8+** -- `pip` 사용 가능 (`python3 -m pip --version` 또는 `python -m pip --version`으로 확인)
- **Langfuse 계정** -- [cloud.langfuse.com](https://cloud.langfuse.com) (무료 플랜 가능) 또는 셀프 호스팅 인스턴스

## 빠른 시작

```bash
# 클론 후 설치 스크립트 실행
git clone https://github.com/BAEM1N/langfuse-claude-code.git
cd langfuse-claude-code
bash install.sh
```

Windows (PowerShell):

```powershell
git clone https://github.com/BAEM1N/langfuse-claude-code.git
cd langfuse-claude-code
.\install.ps1
```

설치 스크립트가 수행하는 작업:
1. Python 3.8+ 설치 확인
2. `langfuse` Python 패키지 설치
3. 훅 스크립트를 `~/.claude/hooks/`에 복사
4. Langfuse 인증 정보 입력 프롬프트:
   - Public Key (`pk-lf-...`)
   - Secret Key (`sk-lf-...`, 마스킹 입력)
   - Base URL (기본값: `https://cloud.langfuse.com`)
   - User ID (기본값: `claude-user`)
5. `~/.claude/settings.json`에 훅 + 환경변수 병합 (기존 설정 보존)
6. 설치 검증

## 수동 설치

### 1. langfuse SDK 설치

```bash
pip install langfuse
```

### 2. 훅 스크립트 복사

```bash
mkdir -p ~/.claude/hooks
cp langfuse_hook.py ~/.claude/hooks/
chmod +x ~/.claude/hooks/langfuse_hook.py
```

### 3. `~/.claude/settings.json` 설정

설정 파일에 다음을 추가(또는 병합)하세요:

```json
{
  "hooks": {
    "Stop": [
      {"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/langfuse_hook.py"}]}
    ],
    "Notification": [
      {"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/langfuse_hook.py"}]}
    ],
    "PreToolUse": [
      {"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/langfuse_hook.py"}]}
    ],
    "PostToolUse": [
      {"hooks": [{"type": "command", "command": "python3 ~/.claude/hooks/langfuse_hook.py"}]}
    ]
  },
  "env": {
    "TRACE_TO_LANGFUSE": "true",
    "LANGFUSE_PUBLIC_KEY": "pk-lf-...",
    "LANGFUSE_SECRET_KEY": "sk-lf-...",
    "LANGFUSE_BASE_URL": "https://cloud.langfuse.com",
    "LANGFUSE_USER_ID": "your-username"
  }
}
```

## 설정

### 환경변수

| 변수 | 필수 | 기본값 | 설명 |
|------|------|--------|------|
| `TRACE_TO_LANGFUSE` | 예 | - | `"true"`로 설정하여 트레이싱 활성화 |
| `LANGFUSE_PUBLIC_KEY` | 예 | - | Langfuse 퍼블릭 키 (`CC_LANGFUSE_PUBLIC_KEY`도 가능) |
| `LANGFUSE_SECRET_KEY` | 예 | - | Langfuse 시크릿 키 (`CC_LANGFUSE_SECRET_KEY`도 가능) |
| `LANGFUSE_BASE_URL` | 아니오 | `https://cloud.langfuse.com` | Langfuse 호스트 URL (`CC_LANGFUSE_BASE_URL`도 가능) |
| `LANGFUSE_USER_ID` | 아니오 | `claude-user` | 트레이스 귀속 사용자 ID (`CC_LANGFUSE_USER_ID`도 가능) |
| `CC_LANGFUSE_DEBUG` | 아니오 | `false` | `"true"`로 설정하면 상세 로깅 활성화 |
| `CC_LANGFUSE_MAX_CHARS` | 아니오 | `20000` | 텍스트 필드당 최대 문자 수 (초과 시 잘림) |

모든 `LANGFUSE_*` 변수는 `CC_LANGFUSE_*` 접두사도 지원합니다 (접두사 버전이 우선).

### 셀프 호스팅 Langfuse

`LANGFUSE_BASE_URL`에 자체 인스턴스 URL을 설정하세요:

```json
"LANGFUSE_BASE_URL": "https://langfuse.your-company.com"
```

## 작동 원리

```
┌─────────────────────────────────────────────────────────┐
│                    Claude Code                          │
│                                                         │
│  사용자 프롬프트 ──► 모델 응답 ──► 도구 호출 ──► ...     │
│       │                                                 │
│       ▼                                                 │
│  트랜스크립트 파일 (.jsonl)                               │
│       │                                                 │
│       │  ┌──── Stop 훅 ─────┐                           │
│       └─►│ langfuse_hook.py │                           │
│          │                   │                           │
│          │ 1. 새 JSONL 읽기  │                           │
│          │ 2. 턴 구성        │                           │
│          │ 3. 트레이스 전송  │                           │
│          └───────┬───────────┘                           │
│                  │                                       │
└──────────────────┼───────────────────────────────────────┘
                   │
                   ▼
          ┌─────────────────────┐
          │      Langfuse        │
          │                      │
          │  Trace (Turn 1)      │
          │  ├─ System Prompt    │
          │  ├─ Generation       │
          │  │   ├─ model        │
          │  │   ├─ usage tokens │
          │  │   └─ stop_reason  │
          │  ├─ Thinking [1]     │
          │  ├─ Text [1]         │
          │  ├─ Tool: Read       │
          │  ├─ Text [2]         │
          │  ├─ Tool: Write      │
          │  └─ Text [3]         │
          │                      │
          │  Session: abc123     │
          └─────────────────────┘
```

**흐름:**

1. Claude Code가 대화 데이터를 JSONL 트랜스크립트 파일에 기록
2. **Stop** 이벤트(모델 응답 후)와 **Notification** 이벤트마다 훅이 트랜스크립트 읽기
3. **PreToolUse**와 **PostToolUse** 이벤트마다 실시간 도구 스팬을 독립적으로 전송
4. 훅이 트랜스크립트에서 **새로운** 줄만 읽음 (상태 파일에 저장된 오프셋 사용)
5. 새 메시지를 사용자-어시스턴트 **턴**으로 그룹화
6. 각 턴을 Langfuse **트레이스**로 전송:
   - **시스템 프롬프트** 스팬 (존재 시)
   - **generation** 관찰 (모델명, 토큰 사용량, stop reason 포함)
   - 어시스턴트 전체 흐름을 순서대로 보존하는 콘텐츠 스팬:
     - **Thinking** 스팬: 내부 추론 블록
     - **Text** 스팬: 도구 호출 사이의 어시스턴트 텍스트
     - **Tool** 스팬: 각 도구 호출 (입출력 포함)
   - 실시간 **Before Tool** / **After Tool** 스팬 (PreToolUse/PostToolUse)
7. 동일 `session_id`로 모든 트레이스 그룹화

## 호환성

| 구성 요소 | 버전 |
|-----------|------|
| Python | 3.8+ |
| langfuse SDK | 2.0+ (플랫 트레이스), 3.12+ (중첩 스팬) |
| Claude Code | hooks 지원하는 모든 버전 |
| OS | macOS, Linux, Windows |

## 문제 해결

### 트레이스가 나타나지 않는 경우

1. 설정에서 `TRACE_TO_LANGFUSE`가 `"true"`인지 확인
2. API 키가 올바른지 확인
3. 디버그 로깅 활성화: `CC_LANGFUSE_DEBUG`를 `"true"`로 설정
4. 로그 파일 확인: `~/.claude/state/langfuse_hook.log`

### 훅이 실행되지 않는 경우

1. `~/.claude/settings.json`의 `hooks.Stop`, `hooks.Notification`, `hooks.PreToolUse`, `hooks.PostToolUse`에 훅이 있는지 확인
2. 커맨드의 Python 경로가 올바른지 확인 (`python3` vs `python`)
3. 수동 테스트: `echo '{}' | python3 ~/.claude/hooks/langfuse_hook.py` (Windows에서는 `python3` 대신 `python` 사용)

### 중복 트레이스

훅이 `~/.claude/state/langfuse_state.json`에 파일 오프셋을 추적합니다. 이 파일을 삭제하면 이전에 전송된 턴이 다시 전송됩니다. 새로 시작하려는 경우에만 상태 파일을 삭제하세요.

### 긴 텍스트 잘림

기본적으로 텍스트 필드는 20,000자에서 잘립니다. `CC_LANGFUSE_MAX_CHARS`로 조정:

```json
"CC_LANGFUSE_MAX_CHARS": "50000"
```

## 제거

1. `~/.claude/settings.json`에서 훅 항목 제거 (`Stop`, `Notification`, `PreToolUse`, `PostToolUse` 훅 및 `env` 키 삭제)
2. 훅 스크립트 삭제: `rm ~/.claude/hooks/langfuse_hook.py`
3. 선택적으로 상태 파일 제거: `rm ~/.claude/state/langfuse_state.json`

## 라이선스

[MIT](LICENSE)
