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
        task => task.status != 'SUCCESS' && task.status != 'FAILED'
      )

      // 无活跃任务时跳过轮询
      if (pendingTasks.length === 0) return

      for (const task of pendingTasks) {
        try {
          const res = await get_task_status(task.id)
          const { status, message } = res

          if (status) {
            if (status === 'SUCCESS' || status === 'ENHANCING') {
              const { markdown, transcript, audio_meta } = res.result
              if (status === 'SUCCESS' && task.status !== 'SUCCESS') {
                toast.success('笔记生成成功')
              }
              const latestMarkdown = latestMarkdownContent(task.markdown)
              if (status !== task.status || message !== task.message || markdown !== latestMarkdown) {
                updateTaskContent(task.id, {
                  status,
                  message,
                  markdown,
                  transcript,
                  audioMeta: audio_meta,
                })
              }
            } else if (status === 'FAILED' && (status !== task.status || message !== task.message)) {
              updateTaskContent(task.id, { status, message })
              console.warn(`任务 ${task.id} 失败`)
            } else if (status !== task.status || message !== task.message) {
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
