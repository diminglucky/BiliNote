import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "app" / "utils" / "note_helper.py"
spec = importlib.util.spec_from_file_location("note_helper", MODULE_PATH)
if spec is None or spec.loader is None:
    raise ImportError("note_helper module spec not found")
note_helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(note_helper)


class TestNoteHelper(unittest.TestCase):
    def test_prepend_source_link_adds_header_at_top(self):
        source_url = "https://www.bilibili.com/video/BV1xx411c7mD"
        markdown = "## 标题\n\n内容"

        result = note_helper.prepend_source_link(markdown, source_url)

        self.assertTrue(result.startswith(f"> 来源链接：{source_url}\n\n"))
        self.assertIn("## 标题", result)

    def test_prepend_source_link_does_not_duplicate_when_header_exists(self):
        source_url = "https://www.youtube.com/watch?v=abc123"
        markdown = f"> 来源链接：{source_url}\n\n## 标题\n\n内容"

        result = note_helper.prepend_source_link(markdown, source_url)

        self.assertEqual(result, markdown)

    def test_replace_content_markers_does_not_create_nested_links_in_toc(self):
        markdown = (
            "## 目录\n\n"
            "- [1. 项目初始化 *Content-[00:00]*](#1-项目初始化-content-0000)\n\n"
            "## 1. 项目初始化 *Content-[00:00]*\n"
            "正文内容\n"
        )

        result = note_helper.replace_content_markers(markdown, "BV123", "bilibili")

        self.assertIn("- [1. 项目初始化 *Content-[00:00]*](#1-项目初始化-content-0000)", result)
        self.assertNotIn("[1. 项目初始化 [原片 @", result)
        self.assertIn("## 1. 项目初始化 [原片 @ 00:00]", result)

    def test_replace_content_markers_keeps_origin_links_outside_toc(self):
        markdown = "## Demo *Content-[04:16]*\n\n正文 Content-[04:20]"

        result = note_helper.replace_content_markers(markdown, "BV123", "bilibili")

        self.assertIn("[原片 @ 04:16]", result)
        self.assertIn("[原片 @ 04:20]", result)

    def test_normalize_markdown_toc_rebuilds_missing_anchor_links(self):
        markdown = (
            "## 目录\n\n"
            "- [RG 系统的核心问题与优化目标 Content-[00:00]]\n"
            "- [1. Simple RG：基础检索增强生成 Content-[00:50]]\n\n"
            "---\n\n"
            "## RG 系统的核心问题与优化目标 *Content-[00:00]\n\n"
            "正文\n\n"
            "## 1. Simple RG：基础检索增强生成 *Content-[00:50]\n\n"
            "正文\n\n"
            "## AI 总结\n\n"
            "总结内容\n"
        )

        result = note_helper.normalize_markdown_toc(markdown, ensure_toc=True)

        self.assertIn(
            "- [RG 系统的核心问题与优化目标 *Content-[00:00]*]"
            "(#rg-系统的核心问题与优化目标-content-0000)",
            result,
        )
        self.assertIn(
            "- [1. Simple RG：基础检索增强生成 *Content-[00:50]*]"
            "(#1-simple-rg基础检索增强生成-content-0050)",
            result,
        )
        self.assertNotIn("- [AI 总结]", result)

    def test_normalize_markdown_toc_adds_toc_when_requested(self):
        markdown = (
            "## 第一节 *Content-[00:01]*\n\n"
            "正文\n\n"
            "## 第二节 *Content-[01:00]*\n"
        )

        result = note_helper.normalize_markdown_toc(markdown, ensure_toc=True)

        self.assertTrue(result.startswith("## 目录\n\n"))
        self.assertIn("- [第一节 *Content-[00:01]*](#第一节-content-0001)", result)
        self.assertIn("- [第二节 *Content-[01:00]*](#第二节-content-0100)", result)


if __name__ == "__main__":
    unittest.main()
