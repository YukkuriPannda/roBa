# slicer-api

FlashPrint 系プリンター向けの、Docker で動くスライス API です。OrcaSlicer を HTTP で呼ぶ上流 [AFKFelix/orca-slicer-api](https://github.com/AFKFelix/orca-slicer-api)（commit `a9a28f0a7b0c6f51b9be158509e9e9677532b868`、tag v0.4.0）を内部コンテナで動かし、その前段に FastAPI のゲートウェイを置いています。

- 対象: FlashForge Adventurer 4 (`ad4`) / Adventurer 5M Pro (`ad5mpro`)
- 公開ポート: ゲートウェイの `127.0.0.1:8080` のみ（既定はループバック）。上流 `orca` は内部ネットワークだけ
- 状態: 実機印刷は未確認。下記「未確認事項」を参照

## 構成

| サービス | 中身 | 役割 |
|---|---|---|
| `orca` | `orca/Dockerfile` で上流コミットをビルド、OrcaSlicer 2.4.2 同梱 | OrcaSlicer CLI の HTTP ラッパー（内部のみ） |
| `gateway` | `Dockerfile`（Python 3.12 / FastAPI、非 root） | ジョブ受付、キュー、出力検証、GX 変換、ダウンロード |

ファイル:

- `app/main.py` API とゲート（API キー、サイズ、キュー上限）、`app/jobs.py` ジョブ管理とパイプライン
- `app/orca_client.py` 上流クライアント、`app/validate.py` 出力検証、`app/gx.py` GX 書き出しと読み込み
- `app/thumbnail.py` サムネイル描画、`app/presets.py` プリンター定義
- `profiles/` 既定プロファイル、`tests/` pytest、`scripts/smoke.sh` `scripts/smoke.ps1` 結合確認

## 起動

```powershell
cd D:\OtherProjects\roBa-case\tools\slicer-api
docker compose up -d --build
# 初回は上流が約 1 分でプロファイルを索引する。/health が 200 になるまで待つ
curl.exe --retry 30 --retry-all-errors --retry-delay 5 http://127.0.0.1:8080/health
```

停止: `docker compose down`（ジョブ データは volume `slicer-data` に残ります）。

### LAN に公開する場合

既定は `127.0.0.1:8080` だけに公開します。LAN から使うには次の 2 つを行ってください。

1. `docker-compose.yml` の `ports` を `"8080:8080"` に変える
2. `API_KEY` を設定する（例: `$env:API_KEY = "長いランダム文字列"` を起動前に設定）。設定すると `GET /health` 以外は `X-API-Key` ヘッダーが必要になります

`API_KEY` が無いまま公開しないでください。

## API

| メソッド・パス | 説明 |
|---|---|
| `GET /health` | `{"status":"ok","orca":true}`。上流に届かなければ 503（`status:"degraded"`） |
| `GET /printers` | 対応プリンター、出力形式 |
| `POST /jobs` | multipart でジョブ投入。`202 {"job_id","status":"queued"}` |
| `GET /jobs/{id}` | 状態。`queued` / `running` / `succeeded` / `failed` |
| `GET /jobs/{id}/files/{name}` | 成果物のダウンロード（`succeeded` のみ、それ以外は 409） |

`POST /jobs` の項目:

- `file`（必須）: `.stl` / `.step` / `.stp` / `.3mf`、100 MB まで
- `printer`（必須）: `ad4` または `ad5mpro`
- `outputs`（任意）: カンマ区切り。プリンターが出せる形式の部分集合（既定は全部）
- `machine_profile` / `process_profile` / `filament_profile`（任意）: JSON ファイル。そのジョブだけ既定値を置き換えます（1 MB まで）

エラー:

- 400: 未知のプリンター、不正な拡張子、不正・不適切な JSON プロファイル、許可されない `outputs`
- 401: `API_KEY` 設定時にキーが無い、または違う
- 413: 100 MB 超（`Content-Length` で早期に拒否）
- 429: 待機中のジョブが `MAX_QUEUED_JOBS`（既定 20）に達している

例:

```bash
curl -F file=@part.stl -F printer=ad4 http://127.0.0.1:8080/jobs
curl http://127.0.0.1:8080/jobs/<job_id>
curl -OJ http://127.0.0.1:8080/jobs/<job_id>/files/part.gx
# API_KEY を設定している場合は -H "X-API-Key: <key>" を付ける
```

動作確認は `scripts/smoke.sh`（bash）か `scripts/smoke.ps1` で行えます。

## プロファイル指定

- 既定: `profiles/<printer>/{machine,process,filament}.json`
- ジョブごとの上書き: `machine_profile` などに JSON を渡す。渡したファイルは既定ファイルの代わりに使われ、マージはしません。
- 上書き JSON の扱い（サーバーが強制する項目）:
  - `type` は種類（machine / process / filament）から自動で設定します
  - `from` と `setting_id` は取り除きます
  - `inherits` は、そのプリンターの system 親に強制します。別の値を書くと 400 です。親がない種類（`ad4` の filament）では `inherits` は書けません
- `name` は空でない文字列が必要です。

### 既定プロファイルと system 親

- `ad5mpro`: OrcaSlicer 2.4.2 の system プロファイルを `inherits` で継承
  - machine: `Flashforge Adventurer 5M Pro 0.4 Nozzle`
  - process: `0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle`
  - filament: `Flashforge Generic PLA`
- `ad4`: 上流の system プロファイルを継承（これらは上流 resources に存在するため、仕様の「system プロファイルなし」は誤りでした）
  - machine: `Flashforge Adventurer 4 Series 0.4 Nozzle` を継承。上書きは `thumbnails` のみ（ファームウェア固有の開始・終了 G-code は system のものを使用）
  - process: `0.20mm Standard @Flashforge AD4 0.4 Nozzle` を継承し、層厚 0.2 mm、3 周、内部充填 15% gyroid を上書き
  - filament: PLA 210 / 215 ℃、ベッド 50 ℃の完全な自作プロファイル（親なし）

## 出力と検証

| 形式 | 対象 | 中身 | 検証 |
|---|---|---|---|
| `gcode` | 両方 | OrcaSlicer 出力 | 空でない、G1 移動がある。下記の移動検査 |
| `3mf` | `ad5mpro` | ZIP（`3D/3dmodel.model`、`Metadata/plate_1.gcode`） | ZIP 整合性、必須メンバー、中の G-code の検証 |
| `gx` | `ad4` | FlashPrint 互換 `.gx`（下記） | 再読込み、オフセット、BMP 80x60 24bit、PNG 320x320、埋め込み G-code が元と一致 |

G-code の移動検査（`app/validate.py`）:

- 大文字小文字を区別せず、行番号 `N…` を無視します。`G0/G00/G1/G01` と `G2/G3` を扱います
- `G90/G91` の絶対・相対を追跡します（Z を含む）。`G92` は位置を再設定、`G28` は位置を不明にします
- AD4 は X/Y が印刷領域（`-110..110` × `-100..100`）内、Z が 0 以上 250 以下であること。円弧は全円の外接箱が領域内に収まること（`I/J` が無い円弧と、位置が不明な円弧は失敗扱い）
- 全プリンター共通で Z < -1 は失敗

検証に失敗したジョブは `failed` になり、成果物は残りません（`error` は 200 文字まで）。

## GX 形式（`app/gx.py`）

リトルエンディアン、58 バイトのヘッダー（`struct '<16s6L8H2B'`）の後に BMP（80x60 24bit）、PNG（320x320）、G-code が続きます。

- マジック `xgcode 1.0\n` + NUL 埋め。`offset_bmp=58`、`offset_png`、`offset_gcode` は各セクションの先頭
- H / B フィールドは書き出し時に各幅の範囲へ収めます（超えた値は範囲端に丸め）
- 印刷時間、フィラメント長、層厚、周数、温度などは G-code 末尾の OrcaSlicer コメントから取得（無い場合は既定値）
- サムネイルは G-code の押し出し移動を真上から描いたもの（Pillow のみ、OpenGL なし）
- 実機の FlashPrint 5 サンプル（`fit_coupon_print.gx`）と同じオフセット（58 / 14512 / 22599）になることをテストで確認

## テスト

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
```

テストは上流を使わずフェイクで API を検証します。GX のサンプル読み込みテストは、サンプルファイルが無い環境ではスキップされます。

## ライセンス注意（AGPL）

- 上流 `AFKFelix/orca-slicer-api` は **AGPL-3.0-or-later** です。ソース: `https://github.com/AFKFelix/orca-slicer-api`、コミット `a9a28f0a7b0c6f51b9be158509e9e9677532b868`（tag v0.4.0）。
- OrcaSlicer 本体も AGPL-3.0 です。`orca` イメージには OrcaSlicer 2.4.2 が含まれます。
- 本リポジトリは上流を別コンテナとして起動し、HTTP 経由でのみ呼び出します。ゲートウェイ（`app/`）は上流のコードを取り込んでいません。
- `orca/Dockerfile` は上流 Dockerfile に対する次の改変を含みます（下記）。上流のソースを改変して配布する場合は、AGPL の義務（対応するソースの提供）を個別に確認してください。

## orca/Dockerfile の改変点（上流との差分）

1. 上流を git で固定コミットから clone する（`UPSTREAM_REF`）。Compose の git コンテキストは使わず、ビルド時に固定コミットであることを検証します。
2. `package.json` を実行イメージの `/app` にコピーする。上流では欠けており、ESM の出力が CommonJS として読まれて起動に失敗するためです。
3. `CMD` を `["node", "dist/index.js"]` にする。上流の `node app/dist/index.js` は存在しないパスです。

## 未確認事項

- 実機印刷は未実施。`ad4` のプロファイル（温度、印刷領域の座標系、system 親の開始・終了 G-code）は **UNVERIFIED** です。試し刷りで確認するまで合格扱いにしないでください。
- GX は読み込み（オフセット、構造、サイズ）で検証しています。FlashPrint での表示は確認していません。
- 上書き JSON はマージではなく置き換えです。`inherits` を使うと system の値を引き継げます。
- ゲートウェイは 1 プロセス（`--workers 1`）前提です。キューは同一プロセス内にあります。
- 上流の `/slice` は同期処理です。`SLICE_TIMEOUT_S`（既定 900 秒）を超えると失敗扱いになります。同時実行数は `MAX_CONCURRENT_JOBS`（既定 1）で制限します。
- ジョブの保存期間は `JOB_RETENTION_HOURS`（既定 24 時間）。終了済みジョブを定期的に削除し、記録のない残骸ディレクトリは 1 時間で掃除します。
