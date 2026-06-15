import { Link, Outlet } from 'react-router-dom'
import { ArrowLeft, Settings } from 'lucide-react'
import React from 'react'
import logo from '@/assets/icon.svg'

interface ISettingLayoutProps {
  Menu: React.ReactNode
}

const SettingLayout = ({ Menu }: ISettingLayoutProps) => {
  return (
    <div className="h-screen w-full overflow-hidden bg-neutral-100 text-neutral-950">
      <div className="flex h-full min-h-0 p-3">
        <aside className="flex w-[300px] shrink-0 flex-col overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm">
          <header className="border-b border-neutral-100 px-5 py-5">
            <div className="mb-5 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-lg border border-neutral-200 bg-white">
                <img src={logo} alt="VideoNote" className="h-full w-full object-contain" />
              </div>
              <div>
                <div className="text-lg font-semibold text-neutral-950">VideoNote</div>
                <div className="text-xs text-neutral-500">配置中心</div>
              </div>
            </div>
            <Link
              to="/"
              className="inline-flex h-9 w-full items-center justify-center gap-2 rounded-md border border-neutral-200 bg-neutral-50 text-sm font-medium text-neutral-700 transition hover:bg-white hover:text-neutral-950"
            >
              <ArrowLeft className="h-4 w-4" />
              返回工作台
            </Link>
          </header>

          <div className="scrollbar-none min-h-0 flex-1 overflow-y-auto p-4">
            <div className="mb-3 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-neutral-400">
              <Settings className="h-3.5 w-3.5" />
              Settings
            </div>
            {Menu}
          </div>
        </aside>

        <main className="ml-3 flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-neutral-200 bg-white shadow-sm">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export default SettingLayout
