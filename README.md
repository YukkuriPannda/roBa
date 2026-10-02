# roBa

## 個人用ケース改造（FreeCAD / PLA）

このフォークではroBa v3を基準に、既存の折り畳みテンティング案をFreeCADで編集・再生成できる構成へ移植しています。

- [FreeCAD版の起動・編集・出力](case/v3/freecad/README.md)
- [自然言語の要望から改造する手順とデータの役割](doc/freecad-workflow.md)
- [PLAの強度チェック・解析・試し刷り](doc/pla-strength-check.md)

基準STEPを保持し、追加形状をパラメーターで管理します。CAD検査の合格と、PLAで印刷した実物の強度・嵌合確認は別に記録します。

roBaは[keyball](https://github.com/Yowkees/keyball/)に影響を受けたワイヤレスキーボードです  
![alt text](doc/img/roba.png)

開発時のブランチ、コミット、承認ルールは[開発・Git運用ガイド](CONTRIBUTING.md)を参照してください。

特徴:
+ ZMK firmwareによるbluetooth(BLE)対応
+ 分割カラムスタッガード配列(キー数:42)
+ トラックボール搭載
+ 水平ロータリーエンコーダ搭載（v1: evqwgd001, v2以降: [CKW12](https://github.com/kumamuk-git/CKW12/tree/main)）

## Where to Buy

[BOOTH](https://kumamuk.booth.pm/)にて組み立てキットが購入可能

## Build Guide

ビルドガイドは[こちら](https://github.com/kumamuk-git/roBa/blob/main/doc/v3/buildguide_v3.md)

## Firmware

ファームウェアのリポジトリは[こちら](https://github.com/kumamuk-git/zmk-config-roBa)  
デフォルトでは以下のように設定されています
+ オートマウスレイヤー：4
+ スクロールレイヤー：5  
+ CPI：400

ファームウェア、キーマップの編集手順は[こちら](https://github.com/kumamuk-git/roBa/blob/main/doc/v3/buildguide_v3.md#6%E3%82%AD%E3%83%BC%E3%83%9E%E3%83%83%E3%83%97%E3%81%AE%E7%B7%A8%E9%9B%86)  
（ZMK STUDIOでもキーマップ編集可能）


