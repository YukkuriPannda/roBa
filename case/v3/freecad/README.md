# roBa v3 FreeCAD ネイティブワークフロー

このフォルダーでは、既存のピンレス折りたたみスタンドと底面側ハードウェアを FreeCAD の `Part` API で再構築します。`case/v3/bottom_L.stp`、`bottom_R.stp`、`top_L.stp`、`top_R.stp` は読み込み専用の参照形状として保持し、元の STEP ファイルや `case/v3/tenting/` 内のファイルは変更しません。

## ビルドと検証

リポジトリのルートで、FreeCAD 1.1 に同梱されている Python を実行します。

```powershell
$freecadBin = Join-Path $env:LOCALAPPDATA 'Programs\FreeCAD 1.1\bin'
& (Join-Path $freecadBin 'python.exe') 'case\v3\freecad\build_verify.py'
```

このコマンドは FreeCAD Python を別プロセスで起動し、FCStd の作成と保存、再オープン後の寸法変更テスト、再度の再オープンと最終検証・エクスポートを行います。成功すると `generated\freecad_build.verified.json`、部品ごとの検証記録、STEP/STL、`generated\roba_v3_folding_tenting.FCStd` を生成します。直近の実行結果は `generated\latest_run_status.json` に記録されます。失敗した場合は直前に成功した成果物を残し、ステータスを `FAIL` にします。残っている成功マニフェストはそこに記載されたハッシュ付き成果物を示すもので、失敗した実行の成果物ではありません。

FreeCAD 同梱の Python を使用し、CadQuery は読み込みません。ビルドには元の STEP ファイルと、既定寸法との回帰確認に使う `case/v3/tenting/output/*.verified.json` が必要です。形状、体積、バウンディングボックス、端点姿勢での干渉、STEP の再読み込み比較、STL メッシュの閉鎖性のいずれかが検査に失敗すると、新しい成果物の公開を中止します。

## ネイティブモデルを開いて編集する

生成後の独立した出力検査と、編集後の出力・不正寸法の拒否は次で再確認できます。後者は `tests/custom-check/` に試験専用のコピーを作り、標準成果物を変更しません。

```powershell
& (Join-Path $freecadBin 'python.exe') 'case\v3\freecad\tests\check_exports.py' .
& (Join-Path $freecadBin 'python.exe') 'case\v3\freecad\tests\check_custom_export.py' .
```

FreeCAD の Macro メニューから `Open_FreeCAD.FCMacro` を実行します。このマクロは FCStd を開く前にこのフォルダーを Python のモジュール検索パスへ追加し、保存済み形状を再計算する `roba_freecad` のプロキシを読み込めるようにします。FCStd がまだない場合は既定寸法のモデルを作成して保存します。初期表示は左側ケースのみです。ツリーでスタンド、右側ケース、上面参照形状を選択して Space キーを押すと、それぞれの表示／非表示を切り替えられます。

`Tenting dimensions (mm / degrees)` オブジェクトに名前付き寸法がまとまっています。`FoldingStand`、`BottomLHardware`、`BottomRHardware` は寸法プロパティに応じて形状を作り直す Python FeaturePython オブジェクトです。`BottomLTenting` と `BottomRTenting` は、再計算された追加ハードウェアを元の底面形状へ結合します。元の左右底面と上面は、それぞれのモデル／参照グループ内に独立した `Part::Feature` のスナップショットとして残ります。STEP を読み込むことで BRep 形状は保持されますが、元のスケッチやフィーチャー履歴は復元されません。

寸法を編集して書き出す場合は、先に FCStd を保存し、FreeCAD の Python コンソールで次を実行します。

```python
from roba_freecad import export_current_document
export_current_document(App.ActiveDocument)
```

このエクスポート処理は、現在の寸法と再計算後の形状を検証してから成果物を更新します。寸法が範囲外の場合や形状検査に失敗した場合はエクスポートを停止し、`generated/latest_run_status.json` に `FAIL` を記録します。

`BaseTentAngle` と元の底面に由来する下面 Z 座標は、既存ケースに対する固定座標変換の参照値です。プロパティエディターでは読み取り専用ですが、Python から意図的に変更すると追加ハードウェアの配置が変わります。読み込んだケース形状そのものは角度変更で回転しません。`DeployAngle` はクリアランス検査に使う端点姿勢だけを指定します。この値を変えても実際のカムストップ形状は変わりません。`NominalTotalTentAngle` は表示用の目標値で、形状を駆動する寸法ではありません。

## 検証の範囲

自動検証では、BRep の有効性と単一ソリッド性、既定寸法での既存検証記録との回帰、元の底面材料が失われていないこと、ピン・ボア・スロートの寸法、折りたたみ／展開の端点姿勢での干渉、STL メッシュの閉鎖性を確認します。STEP 再読み込みでは、体積差を相対 0.02% 以内、`optimalBoundingBox(False, False)` の各辺長の差を 0.02 mm 以内、BRep 頂点とテッセレーション頂点の双方向サンプル距離を 0.005 mm 以内に確認します。これらはサンプルと寸法の回帰確認であり、完全な形状同一性の証明ではありません。ヒンジの全可動範囲は解析しません。また、実機との適合、PLA/PETG の強度、疲労寿命、スナップ力、スライサー挙動、印刷可能性を証明するものではありません。これらは別途レビューと実物での試験が必要です。
