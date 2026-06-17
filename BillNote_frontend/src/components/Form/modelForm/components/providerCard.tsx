import { Switch } from '@/components/ui/switch'
import { FC } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import AILogo from '@/components/Form/modelForm/Icons'
import { useProviderStore } from '@/store/providerStore'

export interface IProviderCardProps {
  id: string
  providerName: string
  Icon: string
  enable: number
}

const ProviderCard: FC<IProviderCardProps> = ({
  providerName,
  Icon,
  id,
}: IProviderCardProps) => {
  const navigate = useNavigate()
  const updateProvider = useProviderStore(state => state.updateProvider)
  const enabled = useProviderStore(state => state.provider.find(p => p.id === id)?.enabled)

  const isChecked = enabled === 1

  const handleToggle = (checked: boolean) => {
    const allProviders = useProviderStore.getState().provider
    const provider = allProviders.find(p => p.id === id)
    if (!provider) return
    updateProvider({
      ...provider,
      enabled: checked ? 1 : 0,
    })
  }

  // @ts-ignore
  const { id: currentId } = useParams()
  const isActive = currentId === id

  return (
    <div
      className={`flex h-14 cursor-pointer items-center justify-between gap-3 rounded-md border px-3 transition ${
        isActive
          ? 'border-blue-200 bg-blue-50 text-blue-700 shadow-sm'
          : 'border-neutral-200 bg-white text-neutral-900 hover:border-neutral-300 hover:bg-neutral-50'
      }`}
      aria-current={isActive ? 'page' : undefined}
      // 整行可点跳转到对应供应商编辑页（之前 onClick 只挂在 icon+名字那一小块 div 上，
      // 名字和开关之间的空白区域点不动）
      onClick={() => navigate(`/settings/model/${id}`)}
    >
      <div className="flex min-w-0 items-center gap-2.5 text-base">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md bg-white">
          <AILogo name={Icon} />
        </div>
        <div className="min-w-0 truncate font-semibold">{providerName}</div>
      </div>

      {/* Switch 自己的点击不应该冒泡触发整行跳转 */}
      <div className="shrink-0" onClick={e => e.stopPropagation()}>
        <Switch
          checked={isChecked}
          onCheckedChange={handleToggle}
        />
      </div>
    </div>
  )
}
export default ProviderCard
