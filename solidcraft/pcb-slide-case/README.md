# PCB スライドケース (SolidCraft 版)

`standalone/pcb-slide-case/build.py`(FreeCAD)の移植。コマンドスクリプトは `slide_case.json`。
本体 `CaseBody` と蓋 `SlidingLid` の2ボディ。座標は外形角が原点、Z 上向き、単位 mm。

## パラメータ (ユーザーパラメータ、形状は式で参照)
InnerWidth=100 / InnerLength=100 / InnerHeight=50 / Wall=3 / Clearance=0.3

## ビルド
```powershell
powershell -File solidcraft\build.ps1
```
`generated/` に STEP / STL / 3MF / iso PNG / eval JSON(`slide_case.eval.json`)を出力する。
STEP/STL/3MF は2ボディを1ファイルに含む。

## 検証結果 (SolidCraft 0.13.1)
- CaseBody bbox 106 x 106 x 62.6、体積 108201.6 mm3(1ソリッド)
- SlidingLid bbox 99.4 x 102.7 x 3、体積 30625.14 mm3(1ソリッド)
- 手計算(FreeCAD 版と同じ形状): 外形 106*106*53=595508 - 空間 100*100*50=500000 = 95508。
  レール 2*(6*106*9.6 - 3*106*3.6)=9921.6、リア 106*3*9.6=3052.8、
  レールとの重なり 2*(6*3*9.6 - 3*3*3.6)=280.8。合計 95508+9921.6+3052.8-280.8=108201.6 (一致)。
  蓋 99.4*102.7*3=30625.14 (一致)。
- `inspect.interference`(CaseBody と SlidingLid、開始位置): 干渉 0 件。
- パラメータ確認: InnerWidth=110 の一時コピーで CaseBody X=116、蓋 X幅 109.4。正本の JSON は 100 のまま。

## 未確認
- FreeCAD 版の体積を実行して比較していない(手計算との一致のみ)。
- スライド全域(120mm 移動)の干渉、保存・再読込、実機の嵌合・PLA強度・スライサー確認。
