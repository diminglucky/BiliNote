import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.agents import AgentExecutionContext, AgentRole, StepExecutionMode, build_note_execution_plan


class TestAgentPlanner(unittest.TestCase):
    def test_plain_note_plan_skips_visual_agents(self):
        plan = build_note_execution_plan(
            AgentExecutionContext(
                task_id="task-1",
                video_url="https://example.com/video",
                platform="youtube",
                quality="medium",
            )
        )

        self.assertEqual(
            plan.step_ids(),
            ("download", "transcript", "write_markdown"),
        )
        self.assertFalse(plan.has_role(AgentRole.VISUAL_ENHANCEMENT))

    def test_screenshot_plan_uses_one_visual_enhancement_step(self):
        plan = build_note_execution_plan(
            AgentExecutionContext(
                task_id="task-1",
                video_url="https://example.com/video",
                platform="bilibili",
                quality="medium",
                formats=("screenshot",),
                screenshot=True,
                defer_screenshots=True,
            )
        )

        steps = {step.step_id: step for step in plan.steps}
        self.assertIn("visual_enhancement", steps)
        self.assertNotIn("build_visual_inventory", steps)
        self.assertNotIn("plan_visuals", steps)
        self.assertNotIn("select_frames", steps)
        self.assertEqual(steps["visual_enhancement"].agent.role, AgentRole.VISUAL_ENHANCEMENT)
        self.assertEqual(steps["visual_enhancement"].mode, StepExecutionMode.BACKGROUND)
        self.assertEqual(steps["visual_enhancement"].depends_on, ("write_markdown",))
        self.assertTrue(steps["visual_enhancement"].optional)

    def test_vision_review_is_an_internal_visual_enhancement_setting(self):
        plan = build_note_execution_plan(
            AgentExecutionContext(
                task_id="task-1",
                video_url="https://example.com/video",
                platform="bilibili",
                quality="medium",
                screenshot=True,
                review_mode="balanced",
            )
        )

        steps = {step.step_id: step for step in plan.steps}
        self.assertIn("visual_enhancement", steps)
        self.assertNotIn("review_frames", steps)
        self.assertEqual(steps["visual_enhancement"].config["review_mode"], "balanced")
        self.assertTrue(any("handled inside visual enhancement" in item for item in plan.diagnostics))

    def test_prefetched_transcript_is_recorded_as_diagnostic(self):
        plan = build_note_execution_plan(
            AgentExecutionContext(
                task_id="task-1",
                video_url="https://example.com/video",
                platform="bilibili",
                quality="medium",
                has_prefetched_transcript=True,
            )
        )

        self.assertTrue(any("prefetched transcript" in item for item in plan.diagnostics))
        transcript = next(step for step in plan.steps if step.step_id == "transcript")
        self.assertTrue(transcript.config["has_prefetched_transcript"])

    def test_plan_can_resolve_steps_by_id(self):
        plan = build_note_execution_plan(
            AgentExecutionContext(
                task_id="task-1",
                video_url="https://example.com/video",
                platform="bilibili",
                quality="medium",
                formats=("link",),
            )
        )

        compose = plan.get_step("compose_markdown")

        self.assertTrue(plan.has_step("compose_markdown"))
        self.assertIsNotNone(compose)
        self.assertTrue(compose.config["include_links"])
        self.assertFalse(plan.has_step("missing_step"))


if __name__ == "__main__":
    unittest.main()
