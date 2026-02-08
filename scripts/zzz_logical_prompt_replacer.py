import os
import re
import json
import modules.scripts as scripts
import gradio as gr
from datetime import datetime
from modules.processing import StableDiffusionProcessing

EXTENSION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SETTINGS_FILE = os.path.join(EXTENSION_ROOT, "logical_prompt_replacer_settings.json")
LOG_DIR = os.path.join(EXTENSION_ROOT, "log")

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_settings(enabled, rules, save_txt):
    settings = {"enabled": enabled, "rules": rules, "save_txt": save_txt}
    try:
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

class PromptModifierScript(scripts.Script):
    def title(self):
        return "Logical Prompt Replacer"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        ID_PREFIX = "logic_modifier_"
        settings = load_settings()
        
        with gr.Accordion("Logical Prompt Replacer", open=True):
            enabled = gr.Checkbox(
                label="有効化", 
                value=settings.get("enabled", True), 
                elem_id=f"{ID_PREFIX}enabled"
            )
            
            rules_text = gr.TextArea(
                label="Rules List",
                placeholder='"blue" => "red" WHEN "night"',
                value=settings.get("rules", ""), 
                lines=10,
                elem_id=f"{ID_PREFIX}rules_text"
            )
            
            with gr.Accordion("Syntax Reference", open=False):
                gr.Markdown("""
                基本構文
                - `探索文字列 => 置換後` （単純置換）
                - `探索文字列 => 置換後 WHEN 条件文字列` （条件付き置換）
                  - プロンプト（Pos+Neg）に条件文字列が含まれる時のみ置換。
                
                文字列と正規表現
                - `"string"` : 文字列 ( エスケープ `\\n`,`\\t`,`\\\\`,`\\"` が必要。大/小文字同一視 )
                - `/pattern/flags` : 正規表現
                  - `i`: 大/小文字同一視
                  - `m`: 複数行判定
                  - `s`: `.` が改行にも一致
                  - `a`: `\\w` が英数字のみに一致
                - 置換後の `$1`, `$2` 等によるグループ参照も有効。
                
                記述例
                - /day/i => "night" WHEN "star"
                - /#.*$/m => "" (コメント除去)
                """)

            save_txt = gr.Checkbox(
                label="プロンプト変化を保存", 
                value=settings.get("save_txt", False), 
                elem_id=f"{ID_PREFIX}save_txt"
            )
            
            gr.Markdown(f"""
                <small>Save Path: 
                    <span style="user-select: all; -webkit-user-select: all; cursor: pointer; font-family: monospace;" title="Click to select all">
                        {LOG_DIR}
                    </span>
                </small>
            """)

            inputs = [enabled, rules_text, save_txt]
            for comp in inputs:
                comp.change(fn=save_settings, inputs=inputs)
            
        return inputs

    @staticmethod
    def extract_value(text):
        if not text: return None
        text = text.strip()
        
        regex_match = re.match(r"^/(.+)/(.*)$", text, re.DOTALL)
        if regex_match:
            pattern, flags_str = regex_match.groups()
            flags = 0
            if 'i' in flags_str: flags |= re.IGNORECASE
            if 'm' in flags_str: flags |= re.MULTILINE
            if 's' in flags_str: flags |= re.DOTALL
            if 'a' in flags_str: flags |= re.ASCII
            try: 
                return re.compile(pattern, flags)
            except Exception: 
                return None
            
        if text.startswith('"') and text.endswith('"'):
            val = text[1:-1]
            try: 
                return val.encode().decode('unicode_escape')
            except Exception: 
                return val
        return text

    def apply_logic_unified(self, pos_prompt, neg_prompt, rules_raw):
        if not rules_raw: return pos_prompt, neg_prompt
        clean_pos = pos_prompt.replace('\r\n', '\n').replace('\r', '\n')
        clean_neg = neg_prompt.replace('\r\n', '\n').replace('\r', '\n')
        combined_for_check = f"{clean_pos} {clean_neg}"

        token_pattern = r'("(?:\\.|[^"])*"|/(?:\\.|[^/])*/[imsayg]*|[^"/\s]+|\s+)'

        for line in rules_raw.split('\n'):
            line = line.strip()
            if not line or line.startswith('#') or "=>" not in line: continue

            tokens = re.findall(token_pattern, line)
            
            # --- 1. WHEN 分割 ---
            when_idx = -1
            for i in range(len(tokens)-1, -1, -1):
                if tokens[i].strip() == "WHEN":
                    when_idx = i
                    break
            
            if when_idx != -1:
                action_part_raw = "".join(tokens[:when_idx]).strip()
                cond_part_raw = "".join(tokens[when_idx+1:]).strip()
            else:
                action_part_raw = line
                cond_part_raw = None

            # --- 2. => 分割 ---
            action_tokens = re.findall(token_pattern, action_part_raw)
            arrow_idx = -1
            for i in range(len(action_tokens)-1, -1, -1):
                if action_tokens[i].strip() == "=>":
                    arrow_idx = i
                    break
            
            if arrow_idx == -1: continue
            
            target_part_raw = "".join(action_tokens[:arrow_idx]).strip()
            repl_part_raw = "".join(action_tokens[arrow_idx+1:]).strip()

            cond_val = self.extract_value(cond_part_raw)
            target_val = self.extract_value(target_part_raw)
            repl_val = self.extract_value(repl_part_raw)
            
            if cond_val is not None:
                if isinstance(cond_val, re.Pattern):
                    if not cond_val.search(combined_for_check): continue
                else:
                    if not re.search(re.escape(str(cond_val)), combined_for_check, re.IGNORECASE):
                        continue

            if target_val is not None:
                r_str = str(repl_val) if repl_val is not None else ""
                if isinstance(target_val, re.Pattern):
                    r_str_fixed = r_str.replace('$', '\\')
                    clean_pos = target_val.sub(r_str_fixed, clean_pos)
                    clean_neg = target_val.sub(r_str_fixed, clean_neg)
                else:
                    pattern = re.escape(str(target_val))
                    clean_pos = re.sub(pattern, r_str, clean_pos, flags=re.IGNORECASE)
                    clean_neg = re.sub(pattern, r_str, clean_neg, flags=re.IGNORECASE)
        
        return clean_pos, clean_neg

    def process(self, p: StableDiffusionProcessing, enabled, rules_text, save_txt):
        if not enabled or not rules_text.strip():
            return
            
        processed_results = [
            self.apply_logic_unified(p.all_prompts[i], p.all_negative_prompts[i], rules_text) 
            for i in range(len(p.all_prompts))
        ]
        
        new_all_prompts = [res[0] for res in processed_results]
        new_all_neg_prompts = [res[1] for res in processed_results]
        
        if save_txt:
            os.makedirs(LOG_DIR, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            for i in range(len(p.all_prompts)):
                orig_pos, edit_pos = p.all_prompts[i], new_all_prompts[i]
                orig_neg, edit_neg = p.all_negative_prompts[i], new_all_neg_prompts[i]
                if orig_pos != edit_pos or orig_neg != edit_neg:
                    log_path = os.path.join(LOG_DIR, f"{timestamp}_{i}.txt")
                    with open(log_path, "w", encoding="utf-8") as f:
                        f.write(f"##### ORIGINAL POSITIVE #####\n\n{orig_pos}\n\n\n\n\n")
                        f.write(f"##### EDITED POSITIVE #####\n\n{edit_pos}\n\n\n\n\n")
                        f.write(f"##### ORIGINAL NEGATIVE #####\n\n{orig_neg}\n\n\n\n\n")
                        f.write(f"##### EDITED NEGATIVE #####\n\n{edit_neg}")
        
        p.all_prompts = new_all_prompts
        p.prompt = new_all_prompts[0]
        p.all_negative_prompts = new_all_neg_prompts
        p.negative_prompt = new_all_neg_prompts[0]