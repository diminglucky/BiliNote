import { taskApi } from '@/services/taskApi'
import type { GenerateNotePayload, GenerateNoteResponse } from '@/services/taskApi'

export type { GenerateNoteResponse }

export const generateNote = (data: GenerateNotePayload): Promise<GenerateNoteResponse> =>
  taskApi.generate(data)

export const delete_task = ({ video_id, platform }: { video_id: string; platform: string }) =>
  taskApi.delete({ video_id, platform })

export const get_task_status = (task_id: string, generation_token?: string) =>
  taskApi.status(task_id, generation_token)
