export const taskStatuses = [
  'PENDING',
  'PARSING',
  'DOWNLOADING',
  'TRANSCRIBING',
  'SUMMARIZING',
  'FORMATTING',
  'ENHANCING',
  'SAVING',
  'SUCCESS',
  'PARTIAL_SUCCESS',
  'FAILED',
] as const

export type TaskStatus = (typeof taskStatuses)[number]

export const taskSteps: Array<{ label: string; key: TaskStatus }> = [
  { label: '解析链接', key: 'PARSING' },
  { label: '下载音频', key: 'DOWNLOADING' },
  { label: '转写文字', key: 'TRANSCRIBING' },
  { label: '总结内容', key: 'SUMMARIZING' },
  { label: '整理截图', key: 'FORMATTING' },
  { label: '增强截图', key: 'ENHANCING' },
  { label: '保存完成', key: 'SUCCESS' },
]

export const terminalTaskStatuses = new Set<TaskStatus>(['SUCCESS', 'PARTIAL_SUCCESS', 'FAILED'])
export const contentReadyStatuses = new Set<TaskStatus>(['SUCCESS', 'PARTIAL_SUCCESS', 'ENHANCING'])

export const isTerminalTaskStatus = (status?: string): status is TaskStatus =>
  Boolean(status && terminalTaskStatuses.has(status as TaskStatus))

export const isFailedTaskStatus = (status?: string) => status === 'FAILED'

export const isSuccessTaskStatus = (status?: string) => status === 'SUCCESS'

export const isPartialSuccessTaskStatus = (status?: string) => status === 'PARTIAL_SUCCESS'

export const isContentReadyTaskStatus = (status?: string) =>
  Boolean(status && contentReadyStatuses.has(status as TaskStatus))

export const isRunningTaskStatus = (status?: string) =>
  Boolean(status && !isTerminalTaskStatus(status))

export const taskStatusMessage = (status?: string, message?: string) => {
  if (message) return message
  if (status === 'ENHANCING') {
    return '正在逐张插入关键截图，笔记内容会自动更新'
  }
  if (status === 'PARTIAL_SUCCESS') {
    return '笔记已完成，部分截图未插入'
  }
  if (status && status !== 'SUCCESS' && status !== 'FAILED') {
    return '正在重新生成，旧笔记会保留到新版本完成'
  }
  return ''
}
