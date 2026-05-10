"""
Full pipeline demo without HTTP server.
Tests the complete agent locally.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from controller.agent import TransportAgent

def demo():
    print("=" * 60)
    print("TRANSPORT AI AGENT — DEMO")
    print("=" * 60)

    agent = TransportAgent()
    session_id = "demo_session_001"

    conversations = [
        "عايز أروح من رمسيس للمطار",
        "أرخص طريقة",
        "طب وإيه لو أسرع؟",
        "وريني أكتر",
        "تفاصيل الأول",
        "كام تعريفة خط 72؟",
        "عايز أروح من المعادي للتحرير",
    ]

    for msg in conversations:
        print(f"\n👤 User: {msg}")
        response = agent.handle(msg, session_id)
        print(f"🤖 Agent:\n{response.text}")
        print("-" * 40)


if __name__ == "__main__":
    demo()