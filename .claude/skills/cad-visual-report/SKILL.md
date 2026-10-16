---
name: cad-visual-report
description: roBa-case で SolidCraft の形状を作成・変更したあと、3面図（等角・正面・上面）、寸法照合表、確認済み／未確認の一覧を1枚のHTMLにまとめ、Artifact として公開してユーザーに報告する。「報告して」「画像で見せて」「結果をまとめて」と言われたとき、または solidcraft/ 以下のスクリプトを変更して検証が終わったときに使う。
---

# CAD 形状の画像つき報告

形状を変えたら、テキストだけで報告せずこの手順で1枚のページにまとめる。

## 担当

- Haiku: 手順1〜3（画像生成、報告JSONの雛形作成、HTML組み立て）。
- Opus: 手順2の `expected` と `checks` の中身を決める。報告JSONの数値を eval 出力と照合する。手順4で公開する。
- サブエージェントは「一致」「済」を自分で決めない。判定は Opus が報告JSONに書く。

## 手順

1. **ビルドと計測**: `powershell -NoProfile -File solidcraft/build.ps1` を実行し、`solidcraft/<part>/generated/<name>.eval.json` が更新されたことを確かめる。
2. **報告JSONを書く**: `solidcraft/<part>/report.json` を書く。形式は下記。
3. **HTMLを生成する**:
   `python -I .claude/skills/cad-visual-report/make_report.py solidcraft/<part>/report.json`
   このコマンドで3面図の撮影（`solidcraft-cli snapshot`）、eval JSON からの外形と体積の読み込み、画像を埋め込んだ HTML の出力までを行う。出力先は `solidcraft/<part>/generated/report.html`。
4. **公開する**: Artifact ツールで `report.html` を公開する。初回は `icon: "cube"` を付ける。同じ部品を更新するときは、同じファイルパスで公開し直して URL を保つ。チャットには URL と、未確認事項を1〜2行で書く。

## report.json の形式

```json
{
  "title": "PCBスライドケース",
  "summary": "何を変えたかを1〜2文で",
  "script": "solidcraft/pcb-slide-case/slide_case.json",
  "eval": "solidcraft/pcb-slide-case/generated/slide_case.eval.json",
  "expected": {"CaseBody": [106, 106, 62.6], "SlidingLid": [99.4, 102.7, 3]},
  "tolerance_mm": 0.01,
  "labels": {"CaseBody": "ケース本体", "SlidingLid": "スライド蓋"},
  "checks": [
    {"status": "done", "text": "ビルドが正常終了"},
    {"status": "todo", "text": "実物の嵌合"}
  ],
  "files": [{"path": "solidcraft/pcb-slide-case/", "note": "スクリプトと生成物"}]
}
```

- `expected` の値は、仕様または手計算から決める。eval の出力をそのまま写さない。
- パラメータ表は eval JSON の `params` から自動で作る。
- 外形の判定は、計測値と `expected` の差が `tolerance_mm` 以内なら「一致」、超えたら「不一致」と自動で表示する。
