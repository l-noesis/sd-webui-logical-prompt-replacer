# Logical Prompt Replacer
Intercepts prompts during the generation process and applies rule-based replacements using Regex and conditional logic.

画像生成時のプロンプトを横取りし、正規表現や条件判定を伴うルールに基づいて自動置換します。


## Background
Dynamic Promptsなどでランダム要素を加えていると、あらかじめ書いておいた固定プロンプトと、ランダム要素が衝突して矛盾してしまうことがあります。

本拡張機能は、そのようなプロンプト同士の衝突を避けるために作成しました。

生成時にプロンプトをチェックし、条件次第でプロンプトを自動的に書き換えます。

## Usage
Rules Listに以下のように記述します。

`"Target" => "Replacement" WHEN "Condition"`

Example:
`/sunny sky/i => "" WHEN "rainy"`
