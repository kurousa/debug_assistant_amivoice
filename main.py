import os
import time
import requests
from openai import OpenAI
from dotenv import load_dotenv
from str_to_bool import str_to_bool


load_dotenv()

# ==========================================
# 1. 設定情報
# ==========================================
AMIVOICE_API_KEY:str = os.getenv("AMIVOICE_API_KEY")
USE_VOICE_RECORD:bool = str_to_bool(os.getenv("USE_VOICE_RECORD"))
LLM_MODEL:str = os.getenv("LLM_MODEL", "qwen2.5-coder:7b")
VOILE_FILENAME: str = "situation_debug_api.mp3"

KNOWLEDGE_FILE = "knowledge_base.md"

class KnowledgeBase:

    # 初期ナレッジ
    INITIAL_KNOWLEDGE:str = """# デバッグナレッジベース

    ## CORSエラー（クロスドメイン制限）
    - **事象**: ブラウザのコンソールにCORSエラーやプリフライトリクエストの失敗（405など）が出る。
    - **原因・対策**: フロントとバックエンドのドメインミスマッチ、またはHTTPメソッドの定義不一致。FastAPI等ではCORSMiddlewareのallow_originsの末尾スラッシュの有無を確認してください。また、カスタムヘッダーを送る場合はallow_headersへ追加してください。
    ---
    """

    def __init__(self, file_path:str = KNOWLEDGE_FILE):
        self.file_path = file_path
    
    def init_knowledge_base(self):
        if not os.path.exists(self.file_path):
            with open(self.file_path, "w", encoding="utf-8") as f:
                f.write(self.INITIAL_KNOWLEDGE)

    def load_all_knowledge(self) -> str:
        with open(self.file_path, "r", encoding="utf-8") as f:
            return f.read()


def record_audio() -> str | None:
    if not USE_VOICE_RECORD:
        return None
    import sounddevice as sd
    from scipy.io import wavfile

    WAV_FILENAME = "debug_voice.wav"
    RECORD_SECONDS = 5
    SAMPLING_RATE = 16000

    print(f"🎤 【デバッグ中...】{RECORD_SECONDS}秒間、独り言をどうぞ！")
    audio_data = sd.rec(int(RECORD_SECONDS * SAMPLING_RATE), samplerate=SAMPLING_RATE, channels=1, dtype='int16')
    sd.wait()
    wavfile.write(WAV_FILENAME, SAMPLING_RATE, audio_data)
    return WAV_FILENAME

def speech_to_text(voile_filename:str) -> str:
    print("🚀 AmiVoice APIで音声認識中...")
    url = "https://acp-api.amivoice.com/v1/recognize"
    params = {"u": AMIVOICE_API_KEY, "d": "-a-general"}
    with open(voile_filename, "rb") as f:
        files = {"a": f}
        response = requests.post(url, params=params, files=files)
    
    if response.status_code == 200:
        text = response.json().get("text", "")
        print(f"🗣️  AmiVoiceの認識結果: 「{text}」")
        return text
    else:
        print(f"❌ AmiVoice API エラー: {response.text}")
        return ""

# Ollamaクライアントの共通初期化
def get_ollama_client():
    return OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")

def ask_local_llm(user_text, all_knowledge):
    print("🤖 ローカルLLMがアドバイスを思考中...")
    client = get_ollama_client()
    
    # systemロールで「日本語の人格」と「絶対ルール」を固定
    system_prompt = """
    あなたはWeb開発のデバッグをサポートする優秀な日本人のシニアエンジニアです。
    【絶対ルール】
    - 回答は必ずすべて【日本語】で出力してください。文章全体を英語で書くことは厳禁です。
    - 日本のエンジニアが親しみやすい、丁寧かつ簡潔な口調（〜です、〜ます）で話してください。
    """
    
    user_prompt = f"""
    開発者が呟いたトラブルの内容と、過去のデバッグ履歴（ナレッジベース）を元に、的確なアドバイスを150文字程度で出力してください。

    【開発者の呟き】
    {user_text}

    【過去のデバッグ履歴】
    {all_knowledge}
    """

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )
    return response.choices[0].message.content

def integrate_and_save_knowledge(user_text, ai_advice, current_knowledge):
    print("🧹 ローカルLLMがナレッジベースの重複を統合・整理中...")
    client = get_ollama_client()
    
    system_prompt = """
    あなたは優秀なテクニカルライターであり、ドキュメント整理のプロフェッショナルです。
    与えられた「既存のMarkdownナレッジベース」に、「今回の新しいデバッグのやり取り」の知見をスマートに統合（マージ）してください。
    
    【ルール】
    - もし既存のセクション（例：CORSエラーなど）と今回の内容が重複している、あるいは関連している場合は、内容を1つにまとめ、より情報が網羅された見出しへとアップデートしてください。
    - 新しい事象であれば、新しい##見出しを作成して追加してください。
    - 出力は【Markdownコードブロックや余計な解説の言葉（「承知しました」など）を一切含めず、純粋なMarkdownテキストのみ】を出力してください。
    - 正しい日本語で出力し、落丁や誤字をなくしてください。
    """
    
    user_prompt = f"""
    【既存のMarkdownナレッジベース】
    {current_knowledge}

    【今回の新しいデバッグのやり取り】
    - 開発者の呟き: {user_text}
    - AIのアドバイス: {ai_advice}
    """

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    )
    
    # 統合された新しいMarkdownでファイルを完全に上書き
    new_markdown = response.choices[0].message.content.strip()
    with open(KNOWLEDGE_FILE, "w", encoding="utf-8") as f:
        f.write(new_markdown)
    print(f"✨ ナレッジベース `{KNOWLEDGE_FILE}` の重複を統合してアップデートしました！")

# ==========================================
# メイン処理
# ==========================================
if __name__ == "__main__":
    # ナレッジベース初期化、ロード
    knowledge_base = KnowledgeBase()
    knowledge_base.init_knowledge_base()
    past_knowledge = knowledge_base.load_all_knowledge()
    
    voile_filename = record_audio()
    # 音声録音を省略した場合は、サンプル音声を利用する
    if voile_filename is None:
        voile_filename = VOILE_FILENAME
    # Amivoice APIによる音声認識
    recognized_text = speech_to_text(voile_filename)
    
    if recognized_text:
        # 1. 日本語でアドバイスを生成
        advice = ask_local_llm(recognized_text, past_knowledge)
        
        print("\n" + "="*40)
        print("💡 シニアエンジニアAIからのアドバイス")
        print("="*40)
        print(advice)
        print("="*40)
        
        # 2. 今回の知見を既存のナレッジと統合して上書き保存
        integrate_and_save_knowledge(recognized_text, advice, past_knowledge)