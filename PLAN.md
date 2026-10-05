# dpcli — план переноса `dp` в переносимую утилиту

Источник: `~/deltaplan/tools/dp` (2667 строк, один файл), `tools/dp.md`, `tools/dp_docs.py`,
`.claude/workflow.md`, `.claude/agents/dp-*.md`, `.claude/skills/start-to-do`.
Цель: папка `.dpcli/` копируется в любой git-проект → `.dpcli/dpcli init` → проект работает
по тому же процессу (главная сессия → координатор модуля → исполнители → приёмка → ревью) без
привязки к Deltaplan.

## Архитектурные решения (контракт для всех исполнителей)

1. **Только стандартная библиотека Python ≥ 3.10.** Язык интерфейса и шаблонов — русский (как в оригинале).
2. **Раскладка дистрибутива** (всё, что копируется в проект):
   ```
   .dpcli/
     dpcli                 # точка входа (python3, исполняемый): добавляет .dpcli в sys.path, dpcli.cli.main()
     dpcli/                # пакет
       __init__.py         # VERSION (бывш. DP_VERSION)
       cli.py              # argparse: build() собирает парсер из register(sp) модулей команд; main()
       config.py           # загрузка dpcli.json | dpcli.yml (+ мини-YAML-парсер), значения по умолчанию
       yamlmini.py         # подмножество YAML: словари, списки, скаляры, комментарии (PyYAML — если есть)
       util.py             # DpError, die, now, read/write json(l), rel, age, short
       gitx.py             # git(), toplevel, worktrees, ветки, merge, commit_paths, main_worktree
       journal.py          # дом модуля, модули, карточки, события, состояния, коды модулей
       agents.py           # чтение определений агентов (frontmatter): роли, review
       reexec.py           # maybe_reexec из главной копии (главный worktree/.dpcli/dpcli)
       commands/
         task.py           # task new|show|set|note|sync, module init
         journal_cmds.py   # event, decide, log, inbox, questions, answer
         accept.py         # accept (+ фоновый)
         report.py         # report, review
         status.py         # status, digest
         plan.py           # plan, plan edit, render
         branches.py       # module new, sync, merge, gc
         search.py         # search, search --sem, index
         jobs.py           # job, lock
         docs.py           # docs check|index|find|show|findings|init (бывш. dp_docs.py)
         init.py           # init: настройка Claude в проекте
     agents/*.md           # определения агентов (источник; init копирует в .claude/agents/)
     skills/<имя>/SKILL.md # скиллы (start-to-do), init копирует в .claude/skills/
     templates/workflow.md # процесс; init рендерит в .claude/dpcli-workflow.md
     templates/claude-md.md# блок для CLAUDE.md (между маркерами <!-- dpcli:begin/end -->)
     dpcli.example.yml     # все ключи конфига с комментариями
     README.md             # установка и справка (бывш. tools/dp.md)
   ```
3. **Конфиг** — `dpcli.json` или `dpcli.yml`/`dpcli.yaml` в корне проекта (ищется вверх от cwd до toplevel
   git; json приоритетнее при обоих). Всё, что было зашито, — ключи с умолчаниями:
   - `project` (имя; по умолч. имя каталога главного worktree), `main_branch` (`main`),
     `module_branch` (`feature/{module}`), `task_branch` (`{module}/{task}`),
   - `copies_dir` (`~`), `module_copy` (`{copies}/{project}-{module}`), `task_copy` (`{copies}/{project}-{module}-{task}`),
   - `plan_dir` (`docs/plan`), `contracts_dir` (`docs/contracts`), `docs_dir` (`docs`),
   - `checks.env` (доп. переменные для проверок; `{tmpdir}` — свежий временный каталог), `checks.tests` (шаблон команды
     для `{tests: …}` в проверках, `{filter}`; нет — проверка `tests` недоступна), `checks.log_dir` (`build/dpcli`),
   - `artifacts_dir` (куда агенты кладут скриншоты/картинки; подсказка в шаблоне отчёта),
   - `reserved_codes` ([]), `gc.ignore_dirs` (`[build, __pycache__]`), `gc.ignore_globs` (`[]`, напр. `*.uid`),
   - `sem` (`model: bge-m3`, `url`, `cache_dir: ~/.cache/dpcli/{project}`, `globs` корпуса),
   - `jobs` (`dir: ~/.cache/dpcli/{project}/jobs`, `tmux_session: dp`, `cpu_slots`), `locks` (каталог замков),
   - `agents_dir` (`.dpcli/agents`), `workflow` (путь к процессу для ссылок в `task show`).
   Переменные окружения `DP_*` переименовываются в `DPCLI_*` (ROLE, LOCAL, NO_REEXEC, SESSION, TASK, CPU_SLOTS, NO_TMUX, TMUX_SESSION, SEM_CPU).
4. **Агенты настраиваются файлами.** `.dpcli/agents/*.md` — обычный формат агента Claude Code (frontmatter
   `name, description, model, effort, tools/disallowedTools, skills`) + ключи dpcli:
   `dpcli_role: coordinator|executor|reviewer|status` и `dpcli_review: true|false` (нужен ли ревьюер после PASS —
   замена REVIEW_TYPES). Тип исполнителя в карточке задачи (`--type`) проверяется по списку агентов с ролью executor.
   Добавить свой тип исполнителя = положить файл и снова `dpcli init`. В тексте агентов — плейсхолдеры
   `{{cli}} {{workflow}} {{plan_dir}} {{contracts_dir}} {{main_branch}} {{module_branch}} {{project}}`, init их подставляет.
5. **`dpcli init`** (идемпотентно, `--dry-run`, `--force`): создать `dpcli.yml` из примера (если конфига нет);
   отрендерить агентов в `.claude/agents/`, скиллы в `.claude/skills/`, процесс в `.claude/dpcli-workflow.md`;
   вписать блок в `CLAUDE.md` между маркерами; добавить в `.claude/settings.json` разрешение `Bash(.dpcli/dpcli *)`;
   дописать в `.gitignore` (`.read_*`, `build/dpcli/`). Чужие изменённые файлы без `--force` не перезаписывать (сообщить).
   Прежний `dp init <модуль>` (только журнал) → **`dpcli module init <модуль>`**.
6. **Перезапуск из главной копии**: вместо зашитого пути — `<главный worktree>/.dpcli/dpcli`, если там VERSION новее.
7. **Убрано как специфика Deltaplan**: Godot (`GODOT_TESTS`, `XDG_DATA_HOME`, `.godot`, `*.uid`), TODO.md/`T`-коды,
   `/home/greg/...`, `dp_migrate.py` (миграция старых `_progress.md`), «физика», пилоты, сайт.
8. Коммиты делает только главная сессия; исполнители не коммитят.

## TODO

- [x] 0. Исследовать исходники, составить план, `git init`
- [ ] 1a. Ядро: config/yamlmini/util/gitx/journal/agents/reexec + разрезание всех команд по `commands/*`, точка входа (агент «core»)
- [ ] 1b. Шаблоны: generic агенты, скилл start-to-do, workflow.md, блок CLAUDE.md, dpcli.example.yml (агент «templates»)
- [ ] 2a. `dpcli init` + интеграция ролей агентов (agents.py ↔ task/report/accept)
- [ ] 2b. `dpcli docs` (порт dp_docs.py, конфигурируемый)
- [ ] 2c. Тесты (unittest, временный git-репозиторий): полный цикл module new → task new → report → accept → review → merge → gc
- [ ] 3. README (справка, бывш. dp.md), сквозная проверка: копия `.dpcli` в пустой проект → init → цикл
- [ ] 4. Ревью кода, грep на остатки deltaplan/godot/greg, финальный коммит
