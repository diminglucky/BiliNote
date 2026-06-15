import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area.tsx'
import logo from '@/assets/icon.svg'

const features = [
  {
    title: '深度笔记生成',
    desc: '围绕视频结构、转写文本和关键知识点生成 Markdown 笔记，减少流水账式摘要。',
  },
  {
    title: '关键截图增强',
    desc: '按笔记内容反推截图位置，过滤空白页、结束页和无关画面，让图片真正服务笔记。',
  },
  {
    title: '异步视觉流程',
    desc: '先交付可阅读笔记，再逐步插入图片，用户可以看到处理进度，不必一直盯着等待。',
  },
  {
    title: '多平台输入',
    desc: '支持 Bilibili、YouTube、抖音、快手和本地视频，适合课程、教程和长视频整理。',
  },
  {
    title: '多模型配置',
    desc: '可接入 OpenAI 兼容供应商、本地转写模型和在线转写服务，按速度与成本自由组合。',
  },
  {
    title: '知识复用',
    desc: '生成后的笔记可导出、生成思维导图，并支持基于笔记内容的问答检索。',
  },
]

export default function AboutPage() {
  const appVersion = __APP_VERSION__

  return (
    <ScrollArea className="h-full overflow-y-auto bg-white">
      <div className="mx-auto max-w-6xl px-6 py-10">
        <section className="mb-10 border-b border-neutral-200 pb-8">
          <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <div className="max-w-3xl">
              <div className="mb-5 flex items-center gap-3">
                <img src={logo} alt="VideoNote Logo" width={48} height={48} className="rounded-lg" />
                <div>
                  <h1 className="text-4xl font-semibold tracking-normal text-neutral-950">
                    VideoNote
                  </h1>
                  <p className="text-sm text-neutral-500">v{appVersion}</p>
                </div>
              </div>
              <p className="text-xl leading-8 text-neutral-700">
                面向视频学习的 AI 笔记工作台。VideoNote 会把视频链接、本地视频、转写文本和关键画面整理成可复用的结构化笔记。
              </p>
            </div>
            <div className="flex flex-wrap gap-2 md:justify-end">
              <Badge variant="secondary">React</Badge>
              <Badge variant="secondary">FastAPI</Badge>
              <Badge variant="secondary">LangGraph</Badge>
              <Badge variant="secondary">Markdown</Badge>
              <Badge variant="secondary">MIT License</Badge>
            </div>
          </div>
        </section>

        <section className="mb-10">
          <h2 className="mb-4 text-2xl font-semibold text-neutral-950">项目定位</h2>
          <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
            <Card>
              <CardContent className="space-y-4 p-6 text-sm leading-7 text-neutral-700">
                <p>
                  VideoNote 不是简单的截图工具，也不是只把字幕交给模型总结。它的目标是先形成完整笔记，再根据笔记段落寻找真正有用的画面，让图文组合能直接进入学习资料。
                </p>
                <p>
                  当前版本重点强化了截图 agent 的选择逻辑、并发控制、失败隔离和前端任务反馈，减少长视频处理时的卡顿感和无关图片。
                </p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-6">
                <div className="grid gap-4 text-sm">
                  <div>
                    <div className="text-neutral-500">默认后端</div>
                    <div className="font-medium text-neutral-950">http://127.0.0.1:8483</div>
                  </div>
                  <div>
                    <div className="text-neutral-500">默认前端</div>
                    <div className="font-medium text-neutral-950">http://127.0.0.1:3015</div>
                  </div>
                  <div>
                    <div className="text-neutral-500">核心输出</div>
                    <div className="font-medium text-neutral-950">Markdown 笔记 + 关键截图 + 思维导图</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </section>

        <section className="mb-10">
          <h2 className="mb-4 text-2xl font-semibold text-neutral-950">核心能力</h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {features.map(feature => (
              <Card key={feature.title} className="h-full">
                <CardContent className="p-5">
                  <h3 className="mb-2 text-base font-semibold text-neutral-950">{feature.title}</h3>
                  <p className="text-sm leading-6 text-neutral-600">{feature.desc}</p>
                </CardContent>
              </Card>
            ))}
          </div>
        </section>

        <section>
          <h2 className="mb-4 text-2xl font-semibold text-neutral-950">本地启动</h2>
          <Tabs defaultValue="manual" className="max-w-3xl">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="manual">手动启动</TabsTrigger>
              <TabsTrigger value="docker">Docker</TabsTrigger>
            </TabsList>
            <TabsContent value="manual" className="mt-4 space-y-4">
              <div className="rounded-md bg-neutral-950 p-4 font-mono text-sm leading-6 text-neutral-100">
                cd backend
                <br />
                pip install -r requirements.txt
                <br />
                python main.py
                <br />
                <br />
                cd BillNote_frontend
                <br />
                pnpm install
                <br />
                pnpm dev
              </div>
            </TabsContent>
            <TabsContent value="docker" className="mt-4 space-y-4">
              <div className="rounded-md bg-neutral-950 p-4 font-mono text-sm leading-6 text-neutral-100">
                docker compose up --build
              </div>
            </TabsContent>
          </Tabs>
        </section>
      </div>
    </ScrollArea>
  )
}
