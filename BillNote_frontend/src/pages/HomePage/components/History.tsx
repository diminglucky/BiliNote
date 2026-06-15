import NoteHistory from '@/pages/HomePage/components/NoteHistory.tsx'
import { useTaskStore } from '@/store/taskStore'
const History = () => {
  const currentTaskId = useTaskStore(state => state.currentTaskId)
  const setCurrentTask = useTaskStore(state => state.setCurrentTask)
  return (
    <div className="h-full w-full">
      <NoteHistory onSelect={setCurrentTask} selectedId={currentTaskId} />
    </div>
  )
}

export default History
