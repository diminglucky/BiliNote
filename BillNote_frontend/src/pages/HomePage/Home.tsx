import { FC, useEffect, useState } from 'react'
import HomeLayout from '@/layouts/HomeLayout.tsx'
import NoteForm from '@/pages/HomePage/components/NoteForm.tsx'
import MarkdownViewer from '@/pages/HomePage/components/MarkdownViewer.tsx'
import { useTaskStore } from '@/store/taskStore'
import History from '@/pages/HomePage/components/History.tsx'
import { isContentReadyTaskStatus, isFailedTaskStatus } from '@/models/taskStateMachine'
type ViewStatus = 'idle' | 'loading' | 'success' | 'failed'
export const HomePage: FC = () => {
  const tasks = useTaskStore(state => state.tasks)
  const currentTaskId = useTaskStore(state => state.currentTaskId)

  const currentTask = tasks.find(t => t.id === currentTaskId)

  const [status, setStatus] = useState<ViewStatus>('idle')
  const hasRenderableContent = Boolean(
    currentTask && currentTask.markdown.length > 0,
  )

  useEffect(() => {
    if (!currentTask) {
      setStatus('idle')
    } else if (
      isContentReadyTaskStatus(currentTask.status) ||
      hasRenderableContent
    ) {
      setStatus('success')
    } else if (isFailedTaskStatus(currentTask.status)) {
      setStatus('failed')
    } else {
      // PENDING、PARSING、DOWNLOADING、TRANSCRIBING、SUMMARIZING 等所有进行中状态
      setStatus('loading')
    }
  }, [currentTask, currentTask?.status, hasRenderableContent])

  return (
    <HomeLayout
      NoteForm={<NoteForm />}
      Preview={<MarkdownViewer status={status} />}
      History={<History />}
    />
  )
}
