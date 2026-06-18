from app.gpt.prompt_builder import generate_base_prompt


def test_screenshot_format_keeps_note_quality_first():
    prompt = generate_base_prompt(
        title="demo",
        segment_text="00:00 - 演示工具安装\n01:00 - 展示运行结果",
        tags=[],
        _format=["screenshot", "link"],
        style="tutorial",
    )

    assert "截图不能反过来破坏文章结构" in prompt
    assert "不要每个章节都插入截图" in prompt
    assert "高质量学习笔记" in prompt
    assert "后续视觉流程会根据正文选择截图" in prompt


def test_base_prompt_requires_document_quality_over_transcript_recap():
    prompt = generate_base_prompt(
        title="demo",
        segment_text="00:00 - 今天我们讲一个系统\n",
        tags=[],
        _format=[],
        style=None,
    )

    assert "先写好文章" in prompt
    assert "不要按字幕逐句复述" in prompt
    assert "截图不是文章结构" in prompt
