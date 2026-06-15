import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import {
  fetchModels,
  addModel,
  fetchEnableModels,
  fetchEnableModelById,
  deleteModelById,
} from '@/services/model'

interface IModel {
  id: string
  created: number
  object: string
  owned_by: string
  permission: string
  root: string
}

interface IModelListItem {
  id: string
  provider_id: string
  model_name: string
  created_at?: string
}

interface ModelStore {
  models: IModel[]
  modelList: IModelListItem[]
  loading: boolean
  selectedModel: string

  loadModels: (providerId: string, opts?: { silent?: boolean }) => Promise<IModel[]>
  loadModelsById: (providerId: string) => Promise<IModelListItem[]>
  loadEnabledModels: () => Promise<void>
  addNewModel: (providerId: string, modelId: string) => Promise<void>
  deleteModel: (modelId: number) => Promise<void>
  setSelectedModel: (modelId: string) => void
  clearModels: () => void
}

export const useModelStore = create<ModelStore>()(
  devtools(set => ({
    models: [],
    modelList: [],
    loading: false,
    selectedModel: '',

    loadEnabledModels: async () => {
      try {
        set({ loading: true })
        const list = await fetchEnableModels()
        set({ modelList: list })
      } catch (error) {
        set({ modelList: [] })
        console.error('加载可用模型失败', error)
      } finally {
        set({ loading: false })
      }
    },

    loadModels: async (providerId: string, opts?: { silent?: boolean }) => {
      try {
        set({ loading: true })
        const res = await fetchModels(providerId, opts)

        let models: IModel[] = []
        if (Array.isArray(res?.models)) {
          models = res.models
        } else if (Array.isArray(res?.models?.data)) {
          models = res.models.data
        }

        set({ models })
        return models
      } catch (error) {
        set({ models: [] })
        console.error('加载模型列表失败', error)
        return []
      } finally {
        set({ loading: false })
      }
    },

    loadModelsById: async (providerId: string) => {
      try {
        const models = await fetchEnableModelById(providerId)
        console.log('获取供应商模型成功', models)
        return models
      } catch (error) {
        console.error('加载供应商模型失败', error)
        return []
      }
    },

    addNewModel: async (providerId: string, modelId: string) => {
      try {
        await addModel({ provider_id: providerId, model_name: modelId })
        console.log('新增模型成功:', modelId)
        set(state => {
          if (state.models.some(model => model.id === modelId)) return state
          return {
            models: [
              ...state.models,
              {
                id: modelId,
                created: Date.now(),
                object: 'model',
                owned_by: '',
                permission: '',
                root: '',
              },
            ],
          }
        })
      } catch (error) {
        console.error('添加模型出错', error)
        throw error
      }
    },

    deleteModel: async (modelId: number) => {
      try {
        await deleteModelById(modelId)
        set(state => ({
          models: state.models.filter(model => model.id !== modelId.toString()),
        }))
      } catch (error) {
        console.error('删除模型失败', error)
      }
    },

    setSelectedModel: (modelId: string) => set({ selectedModel: modelId }),

    clearModels: () => set({ models: [], selectedModel: '', modelList: [] }),
  })),
)
