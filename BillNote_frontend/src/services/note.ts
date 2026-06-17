import request from '@/utils/request'
import toast from 'react-hot-toast'

export interface GenerateNoteResponse {
  task_id: string
  generation_token: string
}

export const generateNote = async (data: {
  video_url: string
  platform: string
  quality: string
  model_name: string
  provider_id: string
  task_id?: string
  format: Array<string>
  style: string
  extras?: string
  video_understanding?: boolean
  video_interval?: number
  grid_size: Array<number>
}): Promise<GenerateNoteResponse> => {
  try {
    console.log('generateNote', data)
    const response = await request.post('/generate_note', data, { timeout: 60000 }) as GenerateNoteResponse | null

    if (!response) {
      throw new Error('Generate note response is empty')
    }

    if (!response.task_id || !response.generation_token) {
      toast.error('后端未返回 generation_token，请重启后端并确认已运行最新代码')
      throw new Error('Generate note response is missing task_id or generation_token')
    }

    console.log('res', response)

    return response
  } catch (e: any) {
    console.error('❌ 请求出错', e)

    // 错误提示
    // toast.error('笔记生成失败，请稍后重试')

    throw e // 抛出错误以便调用方处理
  }
}

export const delete_task = async ({ video_id, platform }) => {
  try {
    const data = {
      video_id,
      platform,
    }
    const res = await request.post('/delete_task', data)


      toast.success('任务已成功删除')
      return res
  } catch (e) {
    toast.error('请求异常，删除任务失败')
    console.error('❌ 删除任务失败:', e)
    throw e
  }
}

export const get_task_status = async (task_id: string, generation_token?: string) => {
  try {
    // 成功提示

    const query = generation_token ? `?generation_token=${encodeURIComponent(generation_token)}` : ''
    return await request.get('/task_status/' + task_id + query, { suppressToast: true })
  } catch (e) {
    console.error('❌ 请求出错', e)

    throw e // 抛出错误以便调用方处理
  }
}
