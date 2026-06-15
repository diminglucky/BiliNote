import Provider from '@/components/Form/modelForm/Provider.tsx'
import { useProviderStore } from '@/store/providerStore'
import { Boxes, PlusCircle } from 'lucide-react'
import { useEffect } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'

const Model = () => {
  const providers = useProviderStore(state => state.provider)
  const location = useLocation()
  const navigate = useNavigate()
  const normalizedPath = location.pathname.replace(/\/$/, '')
  const isModelIndex = normalizedPath.endsWith('/settings/model')

  useEffect(() => {
    if (isModelIndex && providers.length > 0) {
      navigate(providers[0].id, { replace: true })
    }
  }, [isModelIndex, navigate, providers])

  return (
    <div className="grid h-full min-h-0 bg-white lg:grid-cols-[300px_minmax(0,1fr)]">
      <aside className="min-h-0 overflow-hidden border-b border-neutral-200 bg-neutral-50/60 lg:border-r lg:border-b-0">
        <Provider />
      </aside>
      <section className="min-h-0 overflow-hidden bg-white">
        {isModelIndex ? (
          <div className="flex h-full min-h-[420px] items-center justify-center p-8">
            <div className="max-w-md text-center">
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg border border-neutral-200 bg-neutral-50 text-neutral-600">
                {providers.length > 0 ? (
                  <Boxes className="h-5 w-5" />
                ) : (
                  <PlusCircle className="h-5 w-5" />
                )}
              </div>
              <h2 className="mt-4 text-base font-semibold text-neutral-950">
                {providers.length > 0 ? '正在打开模型供应商' : '还没有模型供应商'}
              </h2>
              <p className="mt-2 text-sm leading-6 text-neutral-500">
                {providers.length > 0
                  ? '系统会自动进入第一个供应商详情，你也可以从左侧列表手动选择。'
                  : '点击左侧按钮添加供应商，保存并测试连通性后再启用模型。'}
              </p>
            </div>
          </div>
        ) : (
          <Outlet />
        )}
      </section>
    </div>
  )
}
export default Model
