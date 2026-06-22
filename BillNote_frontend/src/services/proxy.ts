import request from '@/utils/request'

export interface ProxyConfig {
  enabled: boolean
  url: string
  /** 后端实际生效的代理。除设置页外，仅专用环境变量 VIDEONOTE_PROXY_URL 会生效。 */
  effective: string
}

export const getProxyConfig = async (): Promise<ProxyConfig> => {
  return await request.get('/proxy_config')
}

export const updateProxyConfig = async (data: {
  enabled: boolean
  url?: string
}): Promise<ProxyConfig> => {
  return await request.post('/proxy_config', data)
}
