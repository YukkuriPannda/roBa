# 34mmボール用・3点ベアリングケース

通常版 `case/trackballcase.stl` を基準にした派生モデルです。v3通常トップ・右底面を相手形状として使います。元STL、本体STEP、既存テンティングのファイルは変更しません。検査結果は `latest_run_status.json` と実行先の `verification.json` を確認してください。`FAIL_NOT_PRINT_READY` の実行を印刷候補として扱わないでください。

## 出力ファイル

検査に通ったモデルは [`generated/`](generated/) にあります。FreeCADの再計算用モデルは [`trackball_bearing.FCStd`](generated/trackball_bearing.FCStd)、交換用のCAD形状は [`trackball_bearing.step`](generated/trackball_bearing.step)、印刷用メッシュは [`trackball_bearing.stl`](generated/trackball_bearing.stl) です。ビス穴と組付け確認用の試験片は [`fit_coupon.step`](generated/fit_coupon.step) と [`fit_coupon.stl`](generated/fit_coupon.stl)、金属スペーサーの寸法参照形状は [`inner_ring_spacer.stl`](generated/inner_ring_spacer.stl) です。

組立図は [`assembly_preview.png`](generated/assembly_preview.png)、本体との断面確認は [`body_clearance_section.png`](generated/body_clearance_section.png)、支持部断面は [`support_sections.png`](generated/support_sections.png) を参照してください。寸法・入力・コード・成果物のハッシュは [`build.json`](generated/build.json)、CAD検査は [`verification.json`](generated/verification.json)、最終STLのメッシュ検査は [`mesh_export_evidence.json`](generated/mesh_export_evidence.json) に記録しています。

六面図は[PNG](generated/six_view.png)または[印刷用PDF](generated/six_view.pdf)です。第三角法で配置し、各投影に全体寸法を示しています。STLからの正投影図で、製作用の全寸法・公差を指定する図面ではありません。`render_six_view.py` で再生成できます。

## 設計カード

| 項目 | 設定・根拠 |
|---|---|
| ボール | 直径34mm |
| 支持 | 非分離型のラジアル玉軸受3個。内径2.5、外径4.0、幅2.0mm |
| 軸 | M2.5、首下長5mm。小頭ビス、頭径3.8、高さ2.5mm。NBK SNSS-M2.5-5-SDの寸法表を基準にする |
| 内輪保持 | 両側の精密金属スペーサー。内径2.6、外径2.9、厚さ0.4mm、合計6個 |
| 固定先 | 印刷ボスの下穴2.15mm。実部品と試験片で穴・タップ加工・締め付け条件を決める |
| ボール位置 | 元の2mmセラミック球が凹部の平底に接する仮定で復元した中心 `(-0.28458016, 0.09661005, 19.89032338)` mm |
| 本体配置 | 2つの固定穴とセンサー開口を底面の穴に合わせたXY変換。最大残差0.0409mm。Zはフランジ下面と底面上面の接触から設定 |
| 維持するもの | 元の固定耳・M1.7固定穴、下側センサー開口、ボール中心の復元基準、センサー側覆いの大部分 |
| 荷重計算 | 単位下向き荷重あたりの支持反力係数と条件数は [`verification.json`](generated/verification.json) を参照。実荷重、衝撃、樹脂の耐久性は別途実機・試験片で確認 |
| 支持点 | COROPIT写真の「上側に左右2点、反対側下部に1点」の配置と、ベアリング軸が接触点の周方向接線を向く構成を参考にした写真ベースの案。極角98.30/60.00/116.77度、方位角123.58/258.57/358.09度、軸傾き0度。上側2点は元v3のセラミック座位置を継承し、下側は元座の極角28.41度からv3底面との干渉を避けるため60度へ上げた。COROPITの商品ページに座標・軸角寸法やCADは公開されていないため、製品の実測再現ではない。参考: [COROPIT](https://booth.pm/ja/items/6830658) |
| 荷重・印刷条件 | 未確定。PLAの最終強度合格は保留 |

内径・外径・幅だけでは内輪の端面やシールドの寸法は分かりません。**外径2.9mmのスペーサーが内輪だけに接触することを実部品で確認する必要があります。** 実際の内輪端面に合わない場合は、スペーサー径を見直し再生成します。上記スペーサーは金属部品の寸法指定であり、一般のM2.5座金で代用できるという意味ではありません。付属のスペーサーSTLは寸法参照用で、FDM印刷用ではありません。

M2.5ビスのねじ山が内径2.5mmに通ること、軸として支障がないことは実部品で未確認です。ベアリングの外輪・シールドを押さえる締め方は使いません。ねじを強く締めて樹脂ボスを破損させないよう、先に試験片で確認します。

通常の大きな頭ではボールに接触するため、小頭を使います。[NBKのメーカー寸法表](https://www.nbk1560.com/en-US/products/specialscrew/nedzicom/miniaturescrew/SNSS-SD/SNSS-M2.5-SD/)に、首下5mm、頭径3.8mm、頭高さ2.5mmのSNSS-M2.5-5-SDが掲載されています。実際の部品の公差・面取り・首下形状は未確認です。

## 生成と検査

FreeCAD 1.1同梱のPython、NumPy、SciPyを使います。リポジトリのルートで実行します。

```powershell
$freecadBin = Join-Path $env:LOCALAPPDATA 'Programs\FreeCAD 1.1\bin'
& (Join-Path $freecadBin 'python.exe') 'case\v3\freecad\trackball_bearing\build_verify.py'
```

各実行は `runs/<日時>/` に出力します。検査が全て通った実行だけを `generated/` にコピーします。失敗時は `latest_run_status.json` に失敗と実行先を残し、過去の出力を新しい合格として扱いません。STLは0.08mmの形状偏差上限で局所修復し、保存・再読込後の閉鎖性、自己交差、非多様体辺、表面偏差を検査します。直接 `bearing_case.py` を実行した生成物も、検証前は候補です。

元のSTL・本体STEPのハッシュが計測時と異なる場合は停止します。形状が変わった入力に古い支持位置や配置変換を流用しません。寸法を編集した文書を保存しただけでは、STEP/STLと検査結果は更新されません。採用する寸法を生成コードに戻し、再生成・検査してください。

## FreeCADで開く

`Open_Bearing_Case.FCMacro` をFreeCADのMacroメニューから実行します。Pythonモジュールを読み込んでから文書を開くため、寸法変更でケースと相手部品を再計算できます。FCStdだけを別PCに渡さず、このフォルダーのコードとマクロも一緒に渡します。

`Dimensions` にmm・度単位の寸法があります。`BearingCase` とベアリング・ビス・スペーサー・ボール・試験片は、同じ寸法オブジェクトを参照します。`OriginalMesh` は未変更の元STL、`SourceSolid` は局所修復したファセット形状です。元CADのスケッチ履歴を復元したものではありません。

## 元メッシュの修復

元STLには自己交差があります。`repair_source.py` は、その周辺の短い辺を局所的に整理し、閉鎖性を維持した派生メッシュを作ります。変更箇所、面数、体積差、頂点・面重心の双方向サンプル距離を `inspect/logs/repair.json` に記録します。表面サンプル差の上限は0.06mm、体積差の上限は0.05mm³です。完全な表面同一性を証明する検査ではありません。

STLの数値丸めで検査結果が変わるため、修復した基準メッシュはFreeCADネイティブのBMS形式で保持し、保存・再読み込み後も検査します。最終の印刷用STLは別途閉鎖性・非多様体・自己交差を確認します。

## 組み付けと試し刷り

1. `fit_coupon.stl` を本体と同じ材料・条件で試し刷りする。底面の8×8mm台を造形面に置く。
2. 下穴とM2.5ビスを確認する。必要なタップ加工条件を決め、白化・割れ・層間剥離があれば寸法または条件を見直す。
3. ビス頭、金属スペーサー、ベアリング、金属スペーサー、ボスの順に組む。内輪を保持した状態で外輪が軽く回ることを確認する。
4. ケースを試し刷りし、先に3組のベアリングを組み付ける。工具が本体側に通らない箇所は、本体からケースを外して交換する。
5. 元と同じM1.7固定部で取り付け、34mmボールを載せる。3点の接触、ガタ、擦れ、読み取り、配線・基板への接触を実物で確認する。

## 検査の範囲

検査コードは形状・接触・本体干渉・元形状の保持・メッシュ・STEP再読み込み・寸法変更と保存再読み込みを確認します。支持点の力の釣り合いは重力が支持方向の錐に入るかを計算するだけで、PLAの強度・疲労・保持力を証明しません。

センサー穴と元のボール位置の関係は計測基準として保持しますが、PMW3610の光学中心・基板・配線の実モデルはありません。光学距離、実物嵌合、印刷可能性、全体の最小肉厚、耐久性、回転感は未確認です。ボスのボール側には計算上約0.58mmの薄い断面が残るため、強度は保留です。試験片と荷重・造形条件による確認前に、耐荷重部品として採用しないでください。[FreeCAD改造手順](../../../../doc/freecad-workflow.md)と[PLA判定手順](../../../../doc/pla-strength-check.md)に従って試作してください。

## 出典

元のトラックボールケースの出典とCC BY 4.0の帰属は[case/README.md](../../../README.md)を継承します。派生物を配布する際も元作者と改造内容を明記してください。


