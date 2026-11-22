import { Container, Card, CardHeader, CardTitle, CardContent } from '@/components/ui'

export function Chat() {
  return (
    <Container className="py-12">
      <Card>
        <CardHeader>
          <CardTitle>Chat Interface</CardTitle>
        </CardHeader>
        <CardContent>
          <p>Chat interface for asking questions about documents.</p>
        </CardContent>
      </Card>
    </Container>
  )
}