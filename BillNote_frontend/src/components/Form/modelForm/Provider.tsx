import ProviderCard from '@/components/Form/modelForm/components/providerCard.tsx'
import { Button } from '@/components/ui/button.tsx'
import { useProviderStore } from '@/store/providerStore'
import { Plus } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

const Provider = () => {
  const providers = useProviderStore(state => state.provider)
  const navigate = useNavigate()
  const handleClick = () => {
    navigate(`/settings/model/new`)
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-neutral-200 bg-white p-3">
        <Button
          type="button"
          onClick={handleClick}
          className="h-9 w-full rounded-md bg-neutral-950 text-sm text-white hover:bg-neutral-800"
        >
          <Plus className="h-4 w-4" />
          添加模型供应商
        </Button>
      </div>

      <div className="flex items-center justify-between px-3 pt-3 pb-2">
        <div>
          <div className="text-sm font-semibold text-neutral-950">模型供应商</div>
          <div className="text-xs text-neutral-500">{providers.length} 个配置项</div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        <div className="grid gap-2">
          {providers.map(provider => (
            <ProviderCard
              key={provider.id}
              providerName={provider.name}
              Icon={provider.logo}
              id={provider.id}
              enable={provider.enabled}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
export default Provider
