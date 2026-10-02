import { useActions, useValues } from 'kea'

import { IconRewindPlay } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal, LemonTable, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { conversionPeopleLogic } from './conversionPeopleLogic'
import { ConversionPeopleRequestApi, ConversionPersonApi } from './generated/api.schemas'

export function ConversionPeopleModal({
    request,
    goalName,
    onClose,
}: {
    request: ConversionPeopleRequestApi
    goalName: string
    onClose: () => void
}): JSX.Element {
    const logic = conversionPeopleLogic({ request })
    const { page, pageLoading, search } = useValues(logic)
    const { setSearch, loadPeople } = useActions(logic)

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title={`${goalName}: people attributed to ${request.group || '(not set)'}`}
            width={640}
        >
            <LemonModal.Content>
                <div className="flex flex-col gap-4">
                    <LemonInput
                        type="search"
                        fullWidth
                        placeholder="Search by email, name, or ID"
                        value={search}
                        onChange={setSearch}
                    />
                    <p className="text-secondary m-0">A person can have multiple conversions.</p>
                    {page.preparing ? (
                        <LemonBanner type="info">
                            Conversion details are being prepared. Try again in a few minutes.
                        </LemonBanner>
                    ) : page.failed ? (
                        <LemonBanner type="error">Couldn't load conversion details. Try again.</LemonBanner>
                    ) : (
                        <LemonTable<ConversionPersonApi>
                            dataSource={page.results}
                            rowKey="id"
                            loading={pageLoading}
                            columns={[
                                {
                                    title: 'Person',
                                    key: 'person',
                                    render: (_, person) => (
                                        <Link to={urls.personByUUID(person.id)} className="break-all">
                                            {person.name}
                                        </Link>
                                    ),
                                },
                                {
                                    title: '',
                                    key: 'recordings',
                                    render: (_, person) => (
                                        <LemonButton
                                            size="small"
                                            type="secondary"
                                            sideIcon={<IconRewindPlay />}
                                            to={`${urls.personByUUID(person.id)}#activeTab=sessionRecordings`}
                                            tooltip="View this person's recordings"
                                        >
                                            View recordings
                                        </LemonButton>
                                    ),
                                },
                            ]}
                            emptyState={
                                search
                                    ? 'No people match your search. Try another name or email.'
                                    : 'No people found. Refresh the conversion table and try again.'
                            }
                        />
                    )}
                    {(page.has_more || page.preparing || page.failed) && (
                        <LemonButton
                            type="secondary"
                            loading={pageLoading}
                            onClick={() => loadPeople({ append: page.has_more })}
                            center
                            fullWidth
                        >
                            {page.has_more ? 'Load more people' : 'Try again'}
                        </LemonButton>
                    )}
                </div>
            </LemonModal.Content>
        </LemonModal>
    )
}
