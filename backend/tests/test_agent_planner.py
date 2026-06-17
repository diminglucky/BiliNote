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
            ("download", "transcript", "write_markdown", "index_chat"),
        )
        self.assertFalse(plan.has_role(AgentRole.VISUAL_PLANNER))
        self.assertFalse(plan.has_role(AgentRole.FRAME_SELECTOR))

    def test_screenshot_plan_runs_visual_slots_in_background_parallel_steps(self):
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
        self.assertIn("plan_visuals", steps)
        self.assertIn("select_frames", steps)
        self.assertIn("compose_markdown", steps)
        self.assertEqual(steps["plan_visuals"].mode, StepExecutionMode.BACKGROUND)
        self.assertEqual(steps["select_frames"].mode, StepExecutionMode.PARALLEL)
        self.assertEqual(steps["compose_markdown"].depends_on, ("select_frames",))

    def test_vision_review_is_only_enabled_when_review_mode_is_not_off(self):
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
        self.assertIn("review_frames", steps)
        self.assertEqual(steps["review_frames"].agent.role, AgentRole.VISION_REVIEW)
        self.assertEqual(steps["compose_markdown"].depends_on, ("review_frames",))

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
