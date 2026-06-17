import { useEffect, useRef } from 'react'
import { useTaskStore } from '@/store/taskStore'
import { get_task_status } from '@/services/note.ts'
import toast from 'react-hot-toast'

const latestMarkdownContent = (markdown: any): string => {
  if (Array.isArray(markdown)) return markdown[0]?.content || ''
  return typeof markdown === 'string' ? markdown : ''
}

export const useTaskPolling = (interval = 3000) => {
  const tasks = useTaskStore(state => state.tasks)
  const updateTaskContent = useTaskStore(state => state.updateTaskContent)

  const tasksRef = useRef(tasks)

  // 每次 tasks 更新，把最新的 tasks 同步进去
  useEffect(() => {
    tasksRef.current = tasks
  }, [tasks])

  useEffect(() => {
    const timer = setInterval(async () => {
      const pendingTasks = tasksRef.current.filter(
        task => task.status != 'SUCCESS' && task.status != 'FAILED' && !task.isRetrySubmitting
      )

      // 无活跃任务时跳过轮询
      if (pendingTasks.length === 0) return

      for (const task of pendingTasks) {
        try {
          const res = await get_task_status(task.id, task.generationToken)
          const { status, message } = res
          const latestTask = tasksRef.current.find(item => item.id === task.id)
          if (!latestTask || latestTask.isRetrySubmitting) {
            continue
          }
          if (latestTask.generationToken && res.generation_token !== latestTask.generationToken) {
            continue
          }

          if (status) {
            if (status === 'SUCCESS' || status === 'ENHANCING') {
              const { markdown, transcript, audio_meta } = res.result
              if (status === 'SUCCESS' && latestTask.status !== 'SUCCESS') {
                toast.success('笔记生成成功')
              }
              const latestMarkdown = latestMarkdownContent(latestTask.markdown)
              if (status !== latestTask.status || message !== latestTask.message || markdown !== latestMarkdown) {
                updateTaskContent(task.id, {
                  status,
                  message,
                  markdown,
                  transcript,
                  audioMeta: audio_meta,
                })
              }
            } else if (status === 'FAILED' && (status !== latestTask.status || message !== latestTask.message)) {
              updateTaskContent(task.id, { status, message })
              console.warn(`任务 ${task.id} 失败`)
            } else if (status !== latestTask.status || message !== latestTask.message) {
              updateTaskContent(task.id, { status, message })
            }
          }
        } catch (e) {
          console.error('❌ 任务轮询失败：', e)
        }
      }
    }, interval)

    return () => clearInterval(timer)
  }, [interval])
}
